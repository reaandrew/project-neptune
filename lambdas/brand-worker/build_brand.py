#!/usr/bin/env python3
"""Crawl a site once and emit a single brand YAML with style/content/images sections."""

import argparse
import sys
from urllib.parse import urlparse

import yaml

import analyze_style
import scrape_content
import scrape_images
from crawler import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, iter_pages


def build_brand(
    url: str,
    *,
    max_pages: int = 200,
    timeout: int = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_USER_AGENT,
    boilerplate_fraction: float = 0.03,
    min_paragraph_chars: int = 20,
    include_plugin_css: bool = False,
) -> dict:
    """Crawl a site and return the assembled brand dict (style + content + images)."""
    print(f"Crawling {url} (up to {max_pages} pages)...", file=sys.stderr)
    pages = list(iter_pages(url, max_pages, timeout, user_agent))
    print(f"Crawled {len(pages)} pages. Running analyses...", file=sys.stderr)

    style = analyze_style.aggregate_from_pages(
        iter(pages),
        timeout=timeout, user_agent=user_agent,
        skip_noise=not include_plugin_css, start_url=url,
    )
    content = scrape_content.aggregate_from_pages(
        iter(pages),
        boilerplate_fraction=boilerplate_fraction,
        min_paragraph_chars=min_paragraph_chars,
        start_url=url,
    )
    images = scrape_images.aggregate_from_pages(iter(pages), start_url=url)

    return {
        "start_url": url,
        "domain": urlparse(url).netloc,
        "pages_crawled_count": len(pages),
        "style": style,
        "content": content,
        "images": images,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Starting URL (e.g. https://example.com)")
    parser.add_argument("-o", "--output", default="brand.yaml", help="Output YAML file")
    parser.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    parser.add_argument("--boilerplate-fraction", type=float, default=0.03,
                        help="Drop content paragraphs appearing on >= this fraction of pages (default 0.03).")
    parser.add_argument("--min-chars", type=int, default=20,
                        help="Drop content paragraphs shorter than this many characters (default 20).")
    parser.add_argument("--include-plugin-css", action="store_true",
                        help="Include known-noise plugin stylesheets in style analysis.")
    args = parser.parse_args()

    brand = build_brand(
        args.url,
        max_pages=args.max_pages,
        timeout=args.timeout,
        user_agent=args.user_agent,
        boilerplate_fraction=args.boilerplate_fraction,
        min_paragraph_chars=args.min_chars,
        include_plugin_css=args.include_plugin_css,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(brand, f, sort_keys=False, allow_unicode=True, width=120)

    style = brand["style"]
    content = brand["content"]
    images = brand["images"]
    print(
        f"Wrote {args.output}: "
        f"style ({len(style.get('stylesheets_analysed', []))} stylesheets, "
        f"primary {style['brand']['primary_color']}), "
        f"content ({content['unique_paragraphs']} paragraphs), "
        f"images ({images['total_images']} unique).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
