"""Render brand-styled HTML for three popular UI frameworks and
screenshot each so the PDF can include real-world UI samples instead
of ReportLab-drawn box approximations.

Frameworks: Tailwind, Material UI (Material 3 tokens), Bootstrap 5.

Each template lives in ./ui_templates/{framework}.html.tmpl and uses
string.Template-style $name placeholders. We substitute brand colours,
typography, brand name and a logo data-URI, write to a temp file, load
in headless Chromium, take a full-page PNG, and return the path.

If Playwright launch fails (we've seen Chromium SIGSEGV on cold Lambda
boots historically), the whole pass returns {} silently — the PDF
just won't include the framework pages."""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path
from string import Template
from typing import Iterable

import requests


FRAMEWORKS = ("tailwind", "material", "bootstrap")
VIEWPORT_W = 1280
VIEWPORT_H = 920


# ─────────────────────────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────────────────────────
def _hex_to_rgb(hex_: str) -> tuple[int, int, int]:
    h = (hex_ or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return (0, 0, 0)


def _luminance(hex_: str) -> float:
    r, g, b = _hex_to_rgb(hex_)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _contrast_text(hex_: str) -> str:
    return "#0F172A" if _luminance(hex_) > 0.6 else "#FFFFFF"


def _mix_with_white(hex_: str, t: float) -> str:
    r, g, b = _hex_to_rgb(hex_)
    return "#{:02X}{:02X}{:02X}".format(
        int(r + (255 - r) * t),
        int(g + (255 - g) * t),
        int(b + (255 - b) * t),
    )


def _mix_with_black(hex_: str, t: float) -> str:
    r, g, b = _hex_to_rgb(hex_)
    return "#{:02X}{:02X}{:02X}".format(
        int(r * (1 - t)),
        int(g * (1 - t)),
        int(b * (1 - t)),
    )


# ─────────────────────────────────────────────────────────────────
# Logo as inline data-URI (so we don't fight cross-origin issues in
# headless Chromium loading remote PNGs).
# ─────────────────────────────────────────────────────────────────
def _logo_data_uri(logo_url: str | None) -> str | None:
    if not logo_url:
        return None
    try:
        r = requests.get(logo_url, timeout=8, headers={"User-Agent": "brand-worker/1.0"})
        if not r.ok or not r.content:
            return None
        ctype = r.headers.get("Content-Type", "image/png").split(";")[0].strip()
        if not ctype.startswith("image/"):
            ctype = "image/png"
        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:{ctype};base64,{b64}"
    except Exception as e:
        print(f"  ! logo fetch for showcase failed: {e}", file=sys.stderr)
        return None


def _logo_or_mark(logo_uri: str | None, brand_name: str, primary: str, on_primary: str) -> str:
    """HTML snippet showing the brand mark — either the real logo
    served from a data-URI, or a brand-coloured square with the
    first letter when no logo was found."""
    if logo_uri:
        return (
            f'<img src="{logo_uri}" alt="{brand_name}" '
            f'style="height: 36px; width: auto; max-width: 200px; object-fit: contain; '
            f'background: white; border-radius: 6px; padding: 4px 8px;" />'
        )
    initial = (brand_name or "·")[0].upper()
    return (
        f'<div style="width: 36px; height: 36px; border-radius: 8px; '
        f'background: {primary}; color: {on_primary}; display: grid; place-items: center; '
        f'font-family: serif; font-weight: 700; font-size: 18px;">{initial}</div>'
    )


# ─────────────────────────────────────────────────────────────────
# Feature-card mini snippets (one per framework idiom)
# ─────────────────────────────────────────────────────────────────
def _feature_titles(services: list[dict] | None, fallback: list[str]) -> list[str]:
    out = []
    for s in (services or [])[:3]:
        if isinstance(s, dict) and s.get("name"):
            out.append(str(s["name"]))
        elif isinstance(s, str):
            out.append(s)
    while len(out) < 3:
        out.append(fallback[len(out)])
    return out[:3]


def _feature_descs(services: list[dict] | None, fallback: list[str]) -> list[str]:
    out = []
    for s in (services or [])[:3]:
        if isinstance(s, dict) and s.get("description"):
            out.append(str(s["description"]))
        elif isinstance(s, str):
            out.append("")
    while len(out) < 3:
        out.append(fallback[len(out)])
    return out[:3]


def _feature_cards_tailwind(titles: list[str], descs: list[str], primary: str) -> str:
    parts = []
    icons = ["✦", "◆", "●"]
    for i in range(3):
        parts.append(f"""
        <div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm hover:shadow-md transition">
          <div class="w-10 h-10 rounded-xl grid place-items-center mb-4 text-xl text-white" style="background: {primary};">{icons[i]}</div>
          <div class="font-display text-lg font-bold tracking-tight mb-1.5">{titles[i]}</div>
          <p class="text-sm text-slate-600 leading-relaxed">{descs[i]}</p>
        </div>
        """)
    return "\n".join(parts)


def _feature_cards_material(titles: list[str], descs: list[str]) -> str:
    icons = ["bolt", "diamond", "task_alt"]
    parts = []
    for i in range(3):
        parts.append(f"""
        <div class="card">
          <div class="card-media"><span>{icons[i]}</span></div>
          <div class="card-body">
            <div class="card-eyebrow">FEATURE</div>
            <div class="card-title">{titles[i]}</div>
            <p class="card-text">{descs[i]}</p>
          </div>
          <div class="card-actions">
            <button class="btn btn-text">Learn more →</button>
          </div>
        </div>
        """)
    return "\n".join(parts)


def _feature_cards_bootstrap(titles: list[str], descs: list[str]) -> str:
    icons = ["bi-stars", "bi-gem", "bi-check2-circle"]
    parts = []
    for i in range(3):
        parts.append(f"""
        <div class="col-md-4">
          <div class="card border-0 shadow-sm feature-card h-100">
            <div class="card-body p-4">
              <div class="icon-pill mb-3"><i class="bi {icons[i]}"></i></div>
              <h5 class="display-font fw-bold mb-2">{titles[i]}</h5>
              <p class="text-secondary mb-0 small">{descs[i]}</p>
            </div>
          </div>
        </div>
        """)
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────
# Public entry — render + screenshot all 3 frameworks
# ─────────────────────────────────────────────────────────────────
def render_framework_screenshots(
    brand_summary: dict,
    output_dir: Path,
    year: int,
) -> dict[str, Path]:
    """Render each framework template to PNG. Returns {framework: path}
    for the frameworks that succeeded. Failures are logged and skipped
    — the PDF assembly tolerates missing entries.

    brand_summary is the same dict shape ads-worker builds. Required
    keys for a meaningful render:
        brand_name, primary_color, secondary_color, accent_color,
        text_color, primary_font, body_font, primary_logo_url,
        core_services (list).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    primary = (brand_summary.get("primary_color") or "#0F172A").upper()
    secondary = (brand_summary.get("secondary_color") or "#475569").upper()
    accent = (brand_summary.get("accent_color") or primary).upper()
    text_color = (brand_summary.get("text_color") or "#0F172A").upper()
    primary_font = brand_summary.get("primary_font") or "Inter"
    body_font = brand_summary.get("body_font") or primary_font or "Inter"
    brand_name = brand_summary.get("brand_name") or brand_summary.get("domain") or "Brand"
    logo_url = brand_summary.get("primary_logo_url")
    services = brand_summary.get("core_services") or []

    on_primary = _contrast_text(primary)
    primary_soft = _mix_with_white(primary, 0.85)
    primary_pale = _mix_with_white(primary, 0.92)
    primary_dim = _mix_with_black(primary, 0.18)
    pr, pg, pb = _hex_to_rgb(primary)
    primary_rgb = f"{pr},{pg},{pb}"
    primary_text_on_pale = _mix_with_black(primary, 0.30)

    logo_uri = _logo_data_uri(logo_url)
    logo_html = _logo_or_mark(logo_uri, brand_name, primary, on_primary)
    brand_initial = (brand_name or "·")[0].upper()

    titles = _feature_titles(
        services,
        fallback=["Strategy", "Design", "Delivery"],
    )
    descs = _feature_descs(
        services,
        fallback=[
            "What we do for clients on day one.",
            "How we approach the work and the brand.",
            "How we hand it over so it lasts.",
        ],
    )

    common_vars = {
        "primary": primary,
        "primary_soft": primary_soft,
        "primary_pale": primary_pale,
        "primary_dim": primary_dim,
        "primary_rgb": primary_rgb,
        "primary_text_on_pale": primary_text_on_pale,
        "secondary": secondary,
        "accent": accent,
        "text_color": text_color,
        "on_primary": on_primary,
        "display_font": primary_font,
        "display_font_q": primary_font.replace(" ", "+"),
        "body_font": body_font,
        "body_font_q": body_font.replace(" ", "+"),
        "brand_name": brand_name,
        "brand_initial": brand_initial,
        "logo_or_mark": logo_html,
        "feature_cards_tailwind": _feature_cards_tailwind(titles, descs, primary),
        "feature_cards_material": _feature_cards_material(titles, descs),
        "feature_cards_bootstrap": _feature_cards_bootstrap(titles, descs),
        "year": year,
    }

    templates_dir = Path(__file__).parent / "ui_templates"
    out: dict[str, Path] = {}

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"  ! ui-showcase: playwright import failed ({e})", file=sys.stderr)
        return out

    try:
        with sync_playwright() as pw:
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
            ctx = browser.new_context(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})
            for framework in FRAMEWORKS:
                try:
                    tmpl_path = templates_dir / f"{framework}.html.tmpl"
                    html = Template(tmpl_path.read_text(encoding="utf-8")).safe_substitute(common_vars)
                    html_path = output_dir / f"ui-{framework}.html"
                    html_path.write_text(html, encoding="utf-8")
                    page = ctx.new_page()
                    page.goto(html_path.as_uri(), wait_until="networkidle", timeout=30_000)
                    # Tailwind CDN compiles inline JS; give it a beat.
                    page.wait_for_timeout(700)
                    out_path = output_dir / f"ui-{framework}.png"
                    page.screenshot(path=str(out_path), full_page=True)
                    page.close()
                    print(f"  ui-showcase[{framework}]: rendered {out_path.stat().st_size} bytes", file=sys.stderr)
                    out[framework] = out_path
                except Exception as inner:
                    print(f"  ! ui-showcase[{framework}] failed: {inner}", file=sys.stderr)
            browser.close()
    except Exception as e:
        print(f"  ! ui-showcase chromium launch failed: {e}", file=sys.stderr)
        return out

    return out


__all__ = ["render_framework_screenshots", "FRAMEWORKS"]
