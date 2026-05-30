"""Shared BFS site crawler used by scrape_images and scrape_content."""

import sys
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 10
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; site-scraper/1.0)"


def apex(netloc: str) -> str:
    netloc = netloc.lower().split("@")[-1].split(":")[0]
    return netloc[4:] if netloc.startswith("www.") else netloc


def same_domain(url: str, root_apex: str) -> bool:
    return apex(urlparse(url).netloc) == root_apex


def normalize(url: str) -> str:
    """Force https, strip www., drop fragment/trailing slash."""
    parsed = urlparse(urldefrag(url)[0])
    scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme
    netloc = apex(parsed.netloc)
    if parsed.port and not (
        (scheme == "https" and parsed.port == 443) or (scheme == "http" and parsed.port == 80)
    ):
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path.rstrip("/")
    rebuilt = f"{scheme}://{netloc}{path}"
    if parsed.query:
        rebuilt += f"?{parsed.query}"
    return rebuilt


def canonical_image(url: str, root_apex: str) -> str:
    """Same-apex images get full normalize; external images keep their host/scheme."""
    parsed = urlparse(url)
    if apex(parsed.netloc) == root_apex:
        return normalize(url)
    return urldefrag(url)[0]


def iter_pages(start_url: str, max_pages: int = 11, timeout: int = DEFAULT_TIMEOUT,
               user_agent: str = DEFAULT_USER_AGENT,
               first_page_links_only: bool = True):
    """Yields (canonical_url, final_url, html, root_apex).

    By default crawls the start URL plus up to (max_pages - 1) same-domain
    links found ON the start page only. Secondary pages are NOT mined for
    further links — this keeps the crawl bounded and predictable for the
    brand-guidelines pipeline, which only needs a representative slice of
    the site, not an exhaustive map.

    Set first_page_links_only=False to restore the original full BFS
    behaviour."""
    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {start_url!r}")
    root_apex = apex(parsed.netloc)

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    queue = deque([normalize(start_url)])
    visited: set[str] = set()
    seen_first_page = False

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException as exc:
            print(f"[skip] {url}: {exc}", file=sys.stderr)
            continue

        if resp.status_code >= 400:
            print(f"[skip] {url}: HTTP {resp.status_code}", file=sys.stderr)
            continue

        if "html" not in resp.headers.get("Content-Type", "").lower():
            continue

        print(f"[ok]  {url}", file=sys.stderr)
        yield url, resp.url, resp.text, root_apex

        # Only mine the homepage for links — secondary pages are
        # crawled for their content only. Prevents the BFS from
        # ballooning across the whole site (which the brand-guidelines
        # job doesn't need: a representative slice is enough).
        if first_page_links_only and seen_first_page:
            continue
        seen_first_page = True

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            link = normalize(urljoin(resp.url, href))
            if link and link not in visited and same_domain(link, root_apex):
                queue.append(link)
