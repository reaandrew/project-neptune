#!/usr/bin/env python3
"""Crawl a site within a single domain and dump all image URLs to YAML.

Each image is heuristically classified by its DOM location into one of:
  logo, nav, header, footer, sidebar, hero, social, icon, content, other
"""

import argparse
import sys
from collections import Counter, defaultdict
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup

from crawler import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, canonical_image, iter_pages

# Priority: more specific roles win when an image qualifies for multiple.
ROLE_PRIORITY = [
    "logo",
    "social",
    "footer",
    "nav",
    "header",
    "hero",
    "sidebar",
    "icon",
    "content",
    "other",
]

SOCIAL_KEYWORDS = (
    "facebook", "twitter", "instagram", "linkedin",
    "youtube", "tiktok", "pinterest", "whatsapp", "x-logo",
)


def _node_text(el) -> str:
    """Concatenate the class/id/role tokens of an element for keyword matching."""
    if el is None or not hasattr(el, "get"):
        return ""
    parts = []
    cls = el.get("class")
    if cls:
        parts.append(" ".join(cls))
    for attr in ("id", "role"):
        v = el.get(attr)
        if v:
            parts.append(v if isinstance(v, str) else " ".join(v))
    return " ".join(parts).lower()


def _is_small(img) -> bool:
    """True if width/height attribute suggests an icon-sized image."""
    for attr in ("width", "height"):
        v = img.get(attr)
        if v and str(v).strip().rstrip("px").isdigit():
            if int(str(v).strip().rstrip("px")) <= 48:
                return True
    return False


def classify_image(img) -> str:
    """Return the most-specific role label for an <img> based on self + ancestors."""
    # Self-inspection: alt/src/class/id keywords often beat ancestor context for these.
    self_text = " ".join(
        [
            (img.get("alt") or "").lower(),
            (img.get("src") or "").lower(),
            (img.get("data-src") or "").lower(),
            _node_text(img),
        ]
    )
    if "logo" in self_text:
        return "logo"
    if any(k in self_text for k in SOCIAL_KEYWORDS):
        return "social"

    # Ancestor walk: innermost structural match wins.
    for ancestor in img.parents:
        name = getattr(ancestor, "name", None)
        if not name:
            continue
        name = name.lower()
        text = _node_text(ancestor)

        if name == "footer" or "footer" in text or "contentinfo" in text:
            return "footer"
        if name == "nav" or "navigation" in text or "menu" in text or "navbar" in text:
            return "nav"
        if name == "header" or "site-header" in text or "masthead" in text or text.startswith("header "):
            return "header"
        if name == "aside" or "sidebar" in text or "widget-area" in text:
            return "sidebar"
        if any(k in text for k in ("hero", "banner", "slider", "carousel", "jumbotron")):
            return "hero"
        if (
            name in ("main", "article")
            or text == "main"
            or "entry-content" in text
            or "post-content" in text
            or "page-content" in text
            or "site-main" in text
        ):
            # Self-icon override: small image inside content is still likely an icon.
            if "icon" in self_text or _is_small(img):
                return "icon"
            return "content"

    if "icon" in self_text or _is_small(img):
        return "icon"
    return "other"


def best_role(observed: set[str]) -> str:
    for role in ROLE_PRIORITY:
        if role in observed:
            return role
    return "other"


def extract_images(html: str, base_url: str, root_apex: str):
    """Returns a list of (image_url, role, alt) tuples."""
    soup = BeautifulSoup(html, "html.parser")

    image_records: list[tuple[str, str, str]] = []
    seen_on_page: set[str] = set()

    def record(url: str, role: str, alt: str):
        canon = canonical_image(url, root_apex)
        key = (canon, role)
        if key in seen_on_page:
            return
        seen_on_page.add(key)
        image_records.append((canon, role, alt))

    for img in soup.find_all("img"):
        role = classify_image(img)
        alt = (img.get("alt") or "").strip()
        chosen_src = None
        for attr in ("src", "data-src", "data-original"):
            val = img.get(attr)
            if val and val.strip():
                chosen_src = val.strip()
                break
        if chosen_src:
            record(urljoin(base_url, chosen_src), role, alt)
        srcset = img.get("srcset")
        if srcset:
            for part in srcset.split(","):
                candidate = part.strip().split(" ", 1)[0]
                if candidate:
                    record(urljoin(base_url, candidate), role, alt)

    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if not srcset:
            continue
        # <source> inside <picture> — classify via its parent <picture> context.
        proxy_img = source.find_parent("picture") or source
        role = classify_image(proxy_img) if proxy_img.name == "picture" else "other"
        for part in srcset.split(","):
            candidate = part.strip().split(" ", 1)[0]
            if candidate:
                record(urljoin(base_url, candidate), role, "")

    return image_records


def aggregate_from_pages(pages, *, start_url: str | None = None):
    """Process pre-crawled pages and return the images section."""
    visited: list[str] = []
    images_by_page: dict[str, list[dict]] = {}

    roles_for_image: dict[str, set[str]] = defaultdict(set)
    alts_for_image: dict[str, set[str]] = defaultdict(set)
    pages_for_image: dict[str, set[str]] = defaultdict(set)

    for page_url, final_url, html, root_apex in pages:
        visited.append(page_url)
        records = extract_images(html, final_url, root_apex)
        if not records:
            continue
        page_entries = []
        for img_url, role, alt in records:
            page_entries.append({"url": img_url, "role": role, "alt": alt})
            roles_for_image[img_url].add(role)
            if alt:
                alts_for_image[img_url].add(alt)
            pages_for_image[img_url].add(page_url)
        images_by_page[page_url] = page_entries

    # Build aggregated image list
    images_summary = []
    role_counts: Counter = Counter()
    images_by_role: dict[str, list[str]] = defaultdict(list)
    for img_url in sorted(roles_for_image):
        roles = sorted(roles_for_image[img_url], key=lambda r: ROLE_PRIORITY.index(r) if r in ROLE_PRIORITY else 99)
        primary = best_role(roles_for_image[img_url])
        images_summary.append({
            "url": img_url,
            "role": primary,
            "all_roles": roles,
            "alts": sorted(alts_for_image[img_url]),
            "page_count": len(pages_for_image[img_url]),
        })
        role_counts[primary] += 1
        images_by_role[primary].append(img_url)

    for role in images_by_role:
        images_by_role[role].sort()

    return {
        "start_url": start_url,
        "pages_crawled": sorted(set(visited)),
        "total_images": len(images_summary),
        "role_counts": dict(role_counts),
        "images_by_role": dict(images_by_role),
        "images": images_summary,
        "images_by_page": images_by_page,
    }


def crawl(start_url: str, max_pages: int, timeout: int, user_agent: str):
    return aggregate_from_pages(
        iter_pages(start_url, max_pages, timeout, user_agent),
        start_url=start_url,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Starting URL (e.g. https://example.com)")
    parser.add_argument("-o", "--output", default="images.yaml", help="Output YAML file")
    parser.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    args = parser.parse_args()

    result = crawl(args.url, args.max_pages, args.timeout, args.user_agent)

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, allow_unicode=True)

    print(
        f"Crawled {len(result['pages_crawled'])} pages, "
        f"found {result['total_images']} unique images. "
        f"Roles: {result['role_counts']}. "
        f"Wrote {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
