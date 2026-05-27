#!/usr/bin/env python3
"""Crawl a site within a single domain and dump main-content paragraphs to YAML.

Uses trafilatura for boilerplate removal (drops nav, footer, sidebar, cookie
banners, etc.) and main-content extraction.
"""

import argparse
import sys
from collections import Counter

import trafilatura
import yaml

from crawler import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, iter_pages


def extract_paragraphs(html: str, url: str) -> list[str]:
    """Run trafilatura and return cleaned paragraphs as a list of strings."""
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        no_fallback=False,
    )
    if not text:
        return []
    return [p.strip() for p in text.split("\n") if p.strip()]


def extract_title(html: str, url: str) -> str | None:
    md = trafilatura.extract_metadata(html, default_url=url)
    if md and md.title:
        return md.title.strip()
    return None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def aggregate_from_pages(pages, *, boilerplate_fraction: float,
                          min_paragraph_chars: int, start_url: str | None = None):
    """Process pre-crawled pages and return the content section."""
    pages_crawled: list[str] = []
    page_titles: dict[str, str | None] = {}
    para_pages: dict[str, list[str]] = {}

    for page_url, final_url, html, _root in pages:
        pages_crawled.append(page_url)
        paragraphs = [
            p for p in extract_paragraphs(html, final_url)
            if len(p) >= min_paragraph_chars
        ]
        paragraphs = _dedupe_preserve_order(paragraphs)
        if not paragraphs:
            continue
        page_titles[page_url] = extract_title(html, final_url)
        for p in paragraphs:
            para_pages.setdefault(p, []).append(page_url)

    # Cross-page boilerplate: any paragraph appearing on >= threshold pages gets dropped.
    n_pages = len(page_titles)
    if boilerplate_fraction >= 1.0 or n_pages < 4:
        threshold = None
        boilerplate_set: set[str] = set()
    else:
        threshold = max(3, int(n_pages * boilerplate_fraction))
        boilerplate_set = {p for p, pages in para_pages.items() if len(pages) >= threshold}

    paragraphs_out = []
    total_words = 0
    for text, pages in para_pages.items():
        if text in boilerplate_set:
            continue
        paragraphs_out.append({
            "text": text,
            "pages": pages,
            "word_count": len(text.split()),
        })
        total_words += len(text.split())

    boilerplate_list = sorted(
        ({"text": p, "page_count": len(para_pages[p])} for p in boilerplate_set),
        key=lambda x: (-x["page_count"], x["text"]),
    )

    return {
        "start_url": start_url,
        "pages_crawled": sorted(set(pages_crawled)),
        "pages_with_content": n_pages,
        "unique_paragraphs": len(paragraphs_out),
        "total_words": total_words,
        "boilerplate_threshold_pages": threshold,
        "page_titles": dict(sorted(page_titles.items())),
        "boilerplate_removed": boilerplate_list,
        "paragraphs": paragraphs_out,
    }


def crawl(start_url: str, max_pages: int, timeout: int, user_agent: str,
          boilerplate_fraction: float, min_paragraph_chars: int):
    return aggregate_from_pages(
        iter_pages(start_url, max_pages, timeout, user_agent),
        boilerplate_fraction=boilerplate_fraction,
        min_paragraph_chars=min_paragraph_chars,
        start_url=start_url,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Starting URL (e.g. https://example.com)")
    parser.add_argument("-o", "--output", default="content.yaml", help="Output YAML file")
    parser.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    parser.add_argument(
        "--boilerplate-fraction",
        type=float,
        default=0.03,
        help="Drop paragraphs appearing on >= this fraction of pages (default 0.03, floor of 3 pages). Set >=1.0 to disable.",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=20,
        help="Drop paragraphs shorter than this many characters (default 20).",
    )
    args = parser.parse_args()

    result = crawl(
        args.url, args.max_pages, args.timeout, args.user_agent,
        args.boilerplate_fraction, args.min_chars,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, allow_unicode=True, width=120)

    print(
        f"Crawled {len(result['pages_crawled'])} pages, "
        f"{result['pages_with_content']} with content, "
        f"{result['unique_paragraphs']} unique paragraphs, "
        f"{result['total_words']} words. "
        f"Dropped {len(result['boilerplate_removed'])} boilerplate paragraphs "
        f"(threshold {result['boilerplate_threshold_pages']} pages). "
        f"Wrote {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
