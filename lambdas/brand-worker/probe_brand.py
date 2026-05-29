#!/usr/bin/env python3
"""Use Playwright to visit a site and extract the colours/fonts/logo
that are actually visible to a human eye — primary CTA, headings, links,
hero background — and dump them to JSON + a screenshot."""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


PROBE_JS = r"""
() => {
    const norm = (c) => {
        if (!c) return null;
        if (c === 'transparent' || c === 'rgba(0, 0, 0, 0)') return null;
        const m = c.match(/rgba?\(([^)]+)\)/);
        if (!m) return c;
        const parts = m[1].split(',').map(s => s.trim());
        const [r, g, b] = parts.map(Number);
        if (parts.length === 4 && Number(parts[3]) === 0) return null;
        return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
    };

    const sample = (sel, prop) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const cs = getComputedStyle(el);
        return {
            color: norm(cs.color),
            background: norm(cs.backgroundColor),
            font: cs.fontFamily,
            weight: cs.fontWeight,
            size: cs.fontSize,
            text: (el.textContent || '').trim().slice(0, 80),
        };
    };

    const sampleAll = (selectors) => {
        for (const sel of selectors) {
            const r = sample(sel, null);
            if (r) return { selector: sel, ...r };
        }
        return null;
    };

    const tally = (selector, prop) => {
        const map = {};
        document.querySelectorAll(selector).forEach(el => {
            const v = norm(getComputedStyle(el)[prop]);
            if (v) map[v] = (map[v] || 0) + 1;
        });
        return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 10);
    };

    const logos = Array.from(document.querySelectorAll('img'))
        .filter(img => /logo|brand/i.test(img.src + ' ' + img.alt + ' ' + (img.className || '')))
        .slice(0, 8)
        .map(img => ({
            src: img.src,
            alt: img.alt,
            width: img.naturalWidth,
            height: img.naturalHeight,
        }));

    return {
        title: document.title,
        body: sample('body'),
        heading: sampleAll(['h1', 'h2', '.site-title', 'header h1']),
        link: sample('a'),
        button: sampleAll([
            'a.button', 'a.btn', 'button',
            'a[class*="cta"]', 'a[class*="primary"]',
            '.elementor-button', '.wp-block-button__link',
        ]),
        header_bg: sample('header'),
        footer_bg: sample('footer'),
        hero: sampleAll(['.hero', '.banner', '.uk-cover', 'section:first-of-type']),
        top_link_colors: tally('a', 'color'),
        top_button_bgs: tally('a.button, .btn, button, .elementor-button, .wp-block-button__link', 'backgroundColor'),
        top_section_bgs: tally('section, header, footer, .uk-section', 'backgroundColor'),
        top_heading_colors: tally('h1, h2, h3', 'color'),
        logos,
    };
};
"""


GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "-apple-system", "Arial", "Helvetica", "Helvetica Neue"}


def first_real_font(stack: str | None) -> str | None:
    if not stack:
        return None
    for raw in stack.split(","):
        name = raw.strip().strip('"').strip("'")
        if name and name not in GENERIC_FONTS:
            return name
    # fall back to first token if everything was generic
    parts = [p.strip().strip('"').strip("'") for p in stack.split(",") if p.strip()]
    return parts[0] if parts else None


def summarise_probe(probe: dict) -> dict:
    """Distil raw probe output down to display/primary/secondary/accent + fonts + logo."""

    def top_color(entries):
        for c, _ in entries or []:
            if c and c not in ("#000000", "#ffffff", "#f8f8f8", "#fafafa", "#eeeeee", "#cccccc", "#dddddd"):
                return c
        return entries[0][0] if entries else None

    button_bg = top_color(probe.get("top_button_bgs"))
    link_color = top_color(probe.get("top_link_colors"))

    primary = button_bg or link_color
    candidates = [c for c, _ in (probe.get("top_button_bgs") or []) if c not in (primary, "#000000", "#ffffff")]
    candidates += [c for c, _ in (probe.get("top_link_colors") or []) if c not in (primary, "#000000", "#ffffff")]
    secondary = candidates[0] if candidates else None
    accent = None
    for c in candidates[1:]:
        if c not in (primary, secondary):
            accent = c
            break

    heading = probe.get("heading") or {}
    body = probe.get("body") or {}
    display_font = first_real_font(heading.get("font"))
    body_font = first_real_font(body.get("font"))

    logos = probe.get("logos") or []
    own_logos = [l for l in logos if "logo" in (l.get("src") or "").rsplit("/", 1)[-1].lower()]
    primary_logo = (own_logos[0]["src"] if own_logos else (logos[0]["src"] if logos else None))

    return {
        "primary_color": primary,
        "secondary_color": secondary,
        "accent_color": accent,
        "display_font": display_font,
        "body_font": body_font,
        "primary_logo": primary_logo,
        "logo_candidates": [l["src"] for l in logos],
    }


def probe_site(
    url: str,
    *,
    screenshot_dir: str | None = None,
    extra_urls: list[str] | None = None,
) -> dict:
    """Probe the homepage (and optionally extra URLs) — return DOM hints + screenshot paths."""
    screenshots: list[str] = []
    raw: dict = {}
    out = Path(screenshot_dir) if screenshot_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # Lambda-specific Chromium launch args:
        #   --no-sandbox          Lambda runs as root; the sandbox refuses.
        #   --disable-dev-shm-usage  /dev/shm is tiny in Lambda.
        #   --disable-gpu         no GPU available.
        #   --single-process      avoid the multi-process model that
        #                         Lambda's restricted process table
        #                         doesn't handle cleanly.
        #   --no-zygote           pairs with --single-process.
        #   --disable-setuid-sandbox  belt-and-braces with --no-sandbox.
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
            ],
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        # Homepage: probe DOM + capture above-the-fold and full-page shots.
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=60_000)
        try:
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        raw = page.evaluate(PROBE_JS)
        if out:
            fold = out / "01_home_fold.png"
            full = out / "02_home_full.png"
            page.screenshot(path=str(fold), full_page=False)
            page.screenshot(path=str(full), full_page=True)
            screenshots.extend([str(fold), str(full)])

        # Optional inner pages: just full-page captures for visual context.
        for i, extra in enumerate(extra_urls or [], start=1):
            try:
                p2 = ctx.new_page()
                p2.goto(extra, wait_until="networkidle", timeout=60_000)
                if out:
                    fp = out / f"{i + 2:02d}_inner_{i}.png"
                    p2.screenshot(path=str(fp), full_page=False)
                    screenshots.append(str(fp))
                p2.close()
            except Exception as e:
                print(f"  ! couldn't capture {extra}: {e}", file=sys.stderr)

        browser.close()

    raw["summary"] = summarise_probe(raw)
    raw["screenshots"] = screenshots
    return raw


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url")
    p.add_argument("-o", "--output", default="brand_probe.json")
    p.add_argument("--screenshot-dir", default="brand_screenshots")
    p.add_argument("--extra-url", action="append", default=[], help="Additional URL to screenshot")
    args = p.parse_args()

    data = probe_site(args.url, screenshot_dir=args.screenshot_dir, extra_urls=args.extra_url)
    Path(args.output).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} (+{len(data.get('screenshots', []))} screenshots in {args.screenshot_dir})", file=sys.stderr)
    print(json.dumps(data["summary"], indent=2))


if __name__ == "__main__":
    main()
