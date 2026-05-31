#!/usr/bin/env python3
"""Crawl a website and render a brand-guidelines PDF.

Default: pass a URL — the script crawls, analyses, and renders the PDF in one go.
Alternative: pass --from-yaml to reuse an already-built brand YAML.
Optional: pass --save-yaml to also persist the intermediate brand YAML.

Sections (A4 portrait):
  1. Cover                 - brand name + "Brand Guidelines" + year
  2. About                 - one representative paragraph from content
  3. Brand Palette         - primary / secondary / accent / surface / text
  4. Supporting Colors     - remaining palette steps
  5. Typography            - primary display face + type scale
  6. Logos & Marks         - candidate logos downloaded from the site
  7. Favicon               - favicons downloaded from the site
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import analyze_style
import bedrock_brand
import build_brand
import probe_brand
from crawler import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 18 * 2.83465  # 18 mm in points
GUTTER = 8 * 2.83465

HEADER_FONT = "Helvetica-Bold"
BODY_FONT = "Helvetica"
MONO_FONT = "Courier"

# Consultancy producing the guidelines. Defaults to Andrew Rea Associates;
# overridable via --consultancy-* CLI flags for white-label use.
DEFAULT_CONSULTANCY_NAME = "Andrew Rea Associates"
DEFAULT_CONSULTANCY_URL = "andrewreaassociates.com"
DEFAULT_CONSULTANCY_LOGO_URL = "https://andrewreaassociates.com/assets/img/ARA.png"
DEFAULT_CONSULTANCY_TAGLINE = "Brand strategy and design consultancy."


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def contrasting_text(hex_color: str) -> str:
    r, g, b = hex_to_rgb(hex_color)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.55 else "#FFFFFF"


@dataclass
class Swatch:
    label: str
    hex: str
    note: str = ""


def fetch_image(url: str, timeout: int = 15) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "brand-guidelines/1.0"})
        if r.ok and r.content:
            return r.content
    except requests.RequestException:
        return None
    return None


# Cache for the consultancy logo bytes — fetched once, drawn on every page footer.
_CONSULTANCY_LOGO_CACHE: dict[str, bytes | None] = {}


def _get_cached_logo(url: str) -> bytes | None:
    if not url:
        return None
    if url not in _CONSULTANCY_LOGO_CACHE:
        _CONSULTANCY_LOGO_CACHE[url] = fetch_image(url)
    return _CONSULTANCY_LOGO_CACHE[url]


def draw_consultancy_footer_logo(
    c: canvas.Canvas,
    logo_url: str | None,
    fallback_name: str,
    *,
    target_h: float = 18,
    on_dark: bool = False,
    consultancy_url: str = DEFAULT_CONSULTANCY_URL,
) -> None:
    """Bottom-right consultancy mark + URL on every page. Renders the logo
    image with the URL to its left. Falls back to a "Prepared by …" text if
    the logo can't be fetched."""
    data = _get_cached_logo(logo_url) if logo_url else None
    if data:
        try:
            img = ImageReader(io.BytesIO(data))
            iw, ih = img.getSize()
            scale = target_h / ih
            dw = iw * scale
            x = PAGE_W - MARGIN - dw
            y = MARGIN - 22
            if not on_dark:
                pad_x = 8
                pad_y = 5
                c.setFillColor(HexColor("#111111"))
                c.rect(x - pad_x, y - pad_y, dw + 2 * pad_x, target_h + 2 * pad_y,
                       fill=1, stroke=0)
            c.drawImage(img, x, y, dw, target_h, mask="auto")
            # URL to the LEFT of the logo, vertically centred against the logo.
            if consultancy_url:
                c.setFont(BODY_FONT, 9)
                c.setFillColor(white if on_dark else HexColor("#666666"))
                gap = 14 if not on_dark else 8  # leave room for the pill on light pages
                c.drawRightString(x - gap, y + target_h / 2 - 3, consultancy_url)
            return
        except Exception as e:
            print(f"  ! could not render consultancy logo: {e}", file=sys.stderr)
    # Fallback to text only
    c.setFont(BODY_FONT, 8)
    c.setFillColor(white if on_dark else HexColor("#666666"))
    c.drawRightString(PAGE_W - MARGIN, MARGIN - 18,
                      f"Prepared by {fallback_name} · {consultancy_url}")


def brand_name_from(brand: dict, start_url: str) -> str:
    site_name = (brand.get("site_name") or "").strip()
    if site_name:
        return site_name
    host = urlparse(start_url).netloc.lower().lstrip("www.")
    stem = host.split(".")[0]
    return stem.replace("-", " ").replace("_", " ").title()


def draw_page_chrome(
    c: canvas.Canvas,
    section: str,
    page_num: int,
    brand_name: str,
    consultancy_name: str = DEFAULT_CONSULTANCY_NAME,
    consultancy_logo_url: str | None = DEFAULT_CONSULTANCY_LOGO_URL,
) -> None:
    c.setFont(BODY_FONT, 8)
    c.setFillColor(HexColor("#666666"))
    c.drawString(MARGIN, PAGE_H - MARGIN + 14, section)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 14, f"{brand_name} · Brand Guidelines")
    c.drawString(MARGIN, MARGIN - 18, f"{page_num:03d}")
    draw_consultancy_footer_logo(c, consultancy_logo_url, consultancy_name)


def draw_section_title(c: canvas.Canvas, title: str, subtitle: str, y: float) -> float:
    c.setFillColor(black)
    c.setFont(HEADER_FONT, 36)
    c.drawString(MARGIN, y, title)
    if subtitle:
        c.setFont(BODY_FONT, 11)
        c.setFillColor(HexColor("#555555"))
        c.drawString(MARGIN, y - 22, subtitle)
    return y - 60


def draw_tonal_ramp(c: canvas.Canvas, palette: dict, x: float, y: float, w: float, h: float) -> None:
    """Draw a horizontal tonal ramp (50 → 900 steps of a colour family)."""
    if not isinstance(palette, dict) or not palette:
        return
    steps = sorted(palette.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)
    n = len(steps)
    if n == 0:
        return
    sw = w / n
    for i, (key, hex_) in enumerate(steps):
        c.setFillColor(HexColor(hex_))
        c.rect(x + i * sw, y, sw, h, fill=1, stroke=0)
    c.setFillColor(HexColor("#666666"))
    c.setFont(MONO_FONT, 6)
    for i, (key, hex_) in enumerate(steps):
        c.drawCentredString(x + i * sw + sw / 2, y - 8, str(key))


def draw_swatch_row(c: canvas.Canvas, swatches: list[Swatch], y: float, height: float = 130) -> float:
    if not swatches:
        return y
    available = PAGE_W - 2 * MARGIN
    gap = GUTTER
    box_w = (available - gap * (len(swatches) - 1)) / len(swatches)
    x = MARGIN
    for s in swatches:
        c.setFillColor(HexColor(s.hex))
        c.rect(x, y - height, box_w, height, fill=1, stroke=0)
        c.setFillColor(HexColor(contrasting_text(s.hex)))
        c.setFont(HEADER_FONT, 11)
        c.drawString(x + 10, y - 22, s.label.upper())
        c.setFont(MONO_FONT, 10)
        c.drawString(x + 10, y - height + 12, s.hex.upper())
        if s.note:
            c.setFont(BODY_FONT, 8)
            c.drawString(x + 10, y - 36, s.note)
        rgb = hex_to_rgb(s.hex)
        c.setFont(MONO_FONT, 8)
        c.drawString(x + 10, y - height + 26, f"RGB {rgb[0]} {rgb[1]} {rgb[2]}")
        x += box_w + gap
    return y - height - 14


def cover_page(
    c: canvas.Canvas,
    brand_name: str,
    year: int,
    brand_color: str | None = None,
    logo_url: str | None = None,
    screenshot_path: str | None = None,
    consultancy_name: str = DEFAULT_CONSULTANCY_NAME,
    consultancy_logo_url: str | None = DEFAULT_CONSULTANCY_LOGO_URL,
) -> None:
    bg = brand_color or "#000000"
    c.setFillColor(HexColor(bg))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    text_color = contrasting_text(bg)
    c.setFillColor(HexColor(text_color))

    # Reserve a panel on the right side for the homepage screenshot, if
    # available. The text column on the left shrinks accordingly.
    have_screenshot = bool(screenshot_path and Path(screenshot_path).exists())
    panel_w = PAGE_W * 0.45 if have_screenshot else 0
    text_w = PAGE_W - 2 * MARGIN - panel_w

    # Consultancy logo top-left: brand-guidelines books carry the
    # consultancy mark on the cover, not the brand's own logo (the
    # brand's mark is the centrepiece of the Logos & Marks pages later
    # in the book).
    logo_bottom_y = None
    consultancy_data = _get_cached_logo(consultancy_logo_url) if consultancy_logo_url else None
    if consultancy_data:
        try:
            img = ImageReader(io.BytesIO(consultancy_data))
            iw, ih = img.getSize()
            target_h = 60
            scale = target_h / ih
            dw, dh = iw * scale, target_h
            on_dark = (text_color == "#FFFFFF")
            # The ARA mark is dark-on-transparent, so on a dark brand
            # colour we drop it on a small white tile so it stays
            # legible. On a light brand colour we draw it directly.
            x = MARGIN
            y = PAGE_H - MARGIN - dh
            if on_dark:
                pad_x = 10
                pad_y = 8
                c.setFillColor(white)
                c.rect(x - pad_x, y - pad_y, dw + 2 * pad_x, dh + 2 * pad_y,
                       fill=1, stroke=0)
            c.drawImage(img, x, y, dw, dh, mask="auto")
            logo_bottom_y = y - (8 if on_dark else 0)
        except Exception as e:
            print(f"  ! could not render cover consultancy logo: {e}", file=sys.stderr)

    # Year sits directly below the consultancy logo.
    c.setFillColor(HexColor(text_color))
    year_y = (logo_bottom_y - 22) if logo_bottom_y else (PAGE_H - MARGIN - 22)
    c.setFont(BODY_FONT, 14)
    c.drawString(MARGIN, year_y, str(year))

    # The brand's own logo is the centrepiece of the cover — sits in
    # the upper half of the left panel, above the brand name. Drawn
    # directly on the brand colour; for typical web logos this is the
    # mode they were designed for.
    if logo_url:
        brand_data = fetch_image(logo_url)
        if brand_data:
            try:
                img = ImageReader(io.BytesIO(brand_data))
                iw, ih = img.getSize()
                max_w = min(300, text_w * 0.85)
                max_h = 120
                scale = min(max_w / iw, max_h / ih)
                dw, dh = iw * scale, ih * scale
                # Place so the logo sits comfortably above the brand
                # name (whose top edge is around PAGE_H / 2 + 30 for
                # the 56pt title).
                logo_y = PAGE_H / 2 + 60
                c.drawImage(img, MARGIN, logo_y, dw, dh, mask="auto")
            except Exception as e:
                print(f"  ! could not render cover brand logo {logo_url}: {e}", file=sys.stderr)

    # Brand name + subtitle, centred vertically on the left panel.
    # Shrink slightly when a screenshot is squeezing the text column.
    c.setFillColor(HexColor(text_color))
    name_size = 56 if have_screenshot else 64
    c.setFont(HEADER_FONT, name_size)
    c.drawString(MARGIN, PAGE_H / 2 - 30, brand_name)
    c.setFont(BODY_FONT, 22)
    c.drawString(MARGIN, PAGE_H / 2 - 66, "Brand Guidelines")

    # Homepage screenshot panel, right side. PIL crop to the panel
    # aspect ratio so we fill the rectangle without distortion (a plain
    # drawImage would either letterbox or stretch).
    if have_screenshot:
        try:
            from PIL import Image
            panel_x = PAGE_W - panel_w
            panel_y = 0
            panel_h = PAGE_H
            target_ratio = panel_w / panel_h
            with Image.open(screenshot_path) as im:
                im = im.convert("RGB")
                iw, ih = im.size
                src_ratio = iw / ih
                if src_ratio > target_ratio:
                    # Source wider than panel — crop sides, keep centre.
                    new_w = int(ih * target_ratio)
                    left = (iw - new_w) // 2
                    im = im.crop((left, 0, left + new_w, ih))
                else:
                    # Source taller than panel — crop bottom, keep top
                    # (above-the-fold is the most representative part).
                    new_h = int(iw / target_ratio)
                    im = im.crop((0, 0, iw, new_h))
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                buf.seek(0)
                c.drawImage(
                    ImageReader(buf),
                    panel_x, panel_y, panel_w, panel_h,
                    mask="auto",
                )
        except Exception as e:
            print(
                f"  ! could not render cover screenshot {screenshot_path}: {e}",
                file=sys.stderr,
            )

    # No bottom-right consultancy logo on the cover — it sits in the
    # top-left now. Internal pages still carry it in the footer.
    c.showPage()


def about_page(c: canvas.Canvas, brand_name: str, blurb: str, page_num: int) -> None:
    draw_page_chrome(c, "About", page_num, brand_name)
    y = draw_section_title(c, "About", brand_name, PAGE_H - MARGIN - 30)
    c.setFillColor(black)
    c.setFont(BODY_FONT, 12)
    text = c.beginText(MARGIN, y)
    text.setLeading(18)
    max_width = PAGE_W - 2 * MARGIN
    for line in wrap_text(blurb, BODY_FONT, 12, max_width):
        text.textLine(line)
    c.drawText(text)
    c.showPage()


def wrap_text(s: str, font: str, size: float, max_width: float) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = s.split()
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        candidate = " ".join(cur + [w])
        if stringWidth(candidate, font, size) <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def palette_page(c: canvas.Canvas, brand_name: str, brand: dict, palettes: dict, page_num: int) -> None:
    draw_page_chrome(c, "Color Guide", page_num, brand_name)
    y = draw_section_title(
        c,
        "Brand Palette",
        "The brand's colour identity, organised by role. Primary anchors the brand; secondary and accent provide expressive range; surface and text define the foundation.",
        PAGE_H - MARGIN - 30,
    )

    primary = brand.get("primary_color") or "#000000"
    secondary = brand.get("secondary_color") or "#666666"
    accent = brand.get("accent_color") or pick_accent(palettes, primary, secondary)
    surface = brand.get("surface_color") or "#EEEEEE"
    text = brand.get("text_color") or "#111111"
    names = brand.get("color_names") or {}

    row = [
        Swatch(names.get("primary") or "Primary", primary, "anchors brand & CTAs"),
        Swatch(names.get("secondary") or "Secondary", secondary, "supporting voice"),
        Swatch(names.get("accent") or "Accent", accent, "highlights & callouts"),
        Swatch(names.get("surface") or "Surface", surface, "page backgrounds"),
        Swatch(names.get("text") or "Text", text, "body copy"),
    ]
    draw_swatch_row(c, row, y, height=170)
    c.showPage()


def gradients_page(c: canvas.Canvas, brand_name: str, brand: dict, palettes: dict, page_num: int) -> None:
    """One page showing a 50–900 tonal ramp per brand colour (the 'gradients')."""
    draw_page_chrome(c, "Color Guide", page_num, brand_name)
    y = draw_section_title(
        c,
        "Colour Gradients",
        "Each brand colour expanded into a 10-step tonal scale (50 → 900) — lighter tints for surfaces, darker shades for emphasis.",
        PAGE_H - MARGIN - 30,
    )
    names = brand.get("color_names") or {}
    rows = []
    for role in ("primary", "secondary", "accent"):
        palette = (palettes or {}).get(role)
        if not palette:
            base = brand.get(f"{role}_color")
            if base:
                try:
                    palette = analyze_style.tint_shade_palette(base)
                except Exception:
                    palette = None
        if palette:
            rows.append((role, palette, names.get(role) or role.title()))

    if not rows:
        c.setFillColor(HexColor("#666666"))
        c.setFont(BODY_FONT, 11)
        c.drawString(MARGIN, y, "No palettes available.")
        c.showPage()
        return

    available_h = y - MARGIN - 30
    row_h = min(available_h / len(rows), 130)
    ramp_h = row_h - 50
    ramp_w = PAGE_W - 2 * MARGIN
    cur = y
    for role, palette, label in rows:
        cur -= 20
        c.setFillColor(black)
        c.setFont(HEADER_FONT, 14)
        c.drawString(MARGIN, cur, f"{label.upper()}  ·  {role.title()}")
        cur -= 8
        c.setFont(MONO_FONT, 9)
        c.setFillColor(HexColor("#555555"))
        c.drawString(MARGIN, cur, palette.get("500", "").upper())
        cur -= ramp_h
        draw_tonal_ramp(c, palette, MARGIN, cur, ramp_w, ramp_h)
        cur -= 24
    c.showPage()


def pick_accent(palettes: dict, primary: str, secondary: str) -> str:
    primary = primary.lower()
    secondary = secondary.lower()
    candidates = []
    for name, steps in (palettes or {}).items():
        if not isinstance(steps, dict):
            continue
        if name in ("primary", "secondary"):
            continue
        # prefer mid-tone steps
        for k in ("500", "400", "600"):
            v = (steps.get(k) or "").lower()
            if v and v not in (primary, secondary):
                candidates.append(v)
                break
    return candidates[0] if candidates else "#F7823D"


def supporting_pages(
    c: canvas.Canvas, brand_name: str, palettes: dict, brand: dict, start_page: int
) -> int:
    used = {(brand.get("primary_color") or "").lower(), (brand.get("secondary_color") or "").lower()}
    swatches: list[Swatch] = []
    for name, steps in (palettes or {}).items():
        if not isinstance(steps, dict):
            continue
        for k, v in steps.items():
            if not v or v.lower() in used:
                continue
            used.add(v.lower())
            swatches.append(Swatch(f"{name.title()} {k}", v))
    page = start_page
    per_page = 9  # 3 rows x 3 cols
    for i in range(0, len(swatches), per_page):
        chunk = swatches[i : i + per_page]
        draw_page_chrome(c, "Color Guide", page, brand_name)
        y = draw_section_title(
            c,
            "Supporting Colours",
            "Additional tones detected on the site — useful as tints, charts, or backup accents.",
            PAGE_H - MARGIN - 30,
        )
        for row_start in range(0, len(chunk), 3):
            row = chunk[row_start : row_start + 3]
            y = draw_swatch_row(c, row, y, height=110)
        c.showPage()
        page += 1
    return page


def design_dna_page(
    c: canvas.Canvas,
    brand_name: str,
    design_dna: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Render the brand's design DNA — archetype, density, typographic
    voice, photographic treatment, layout preference, reference marks,
    voice-to-design rules and do-nots. Returns next page number.
    Silently skipped (returns page_num unchanged) if no DNA is set."""
    if not design_dna or not design_dna.get("archetype"):
        return page_num

    draw_page_chrome(c, "Design DNA", page_num, brand_name)
    y = draw_section_title(
        c,
        "Design DNA",
        "The visual contract every piece of brand work should obey. Drives the ad generator and any future creative.",
        PAGE_H - MARGIN - 30,
    )

    accent = HexColor(primary_color)
    text_on_accent = HexColor(contrasting_text(primary_color))
    label_grey = HexColor("#666666")
    body_grey = HexColor("#333333")

    col_gap = GUTTER
    col_w = (PAGE_W - 2 * MARGIN - col_gap) / 2
    left_x = MARGIN
    right_x = MARGIN + col_w + col_gap

    # ── Top band: archetype hero (left) + density pill row (right) ─
    archetype = design_dna.get("archetype") or ""
    archetype_label = archetype.replace("-", " ").upper()
    arch_box_h = 90

    # Left: archetype hero block
    c.setFillColor(accent)
    c.rect(left_x, y - arch_box_h, col_w, arch_box_h, fill=1, stroke=0)
    c.setFillColor(text_on_accent)
    c.setFont(HEADER_FONT, 9)
    c.drawString(left_x + 14, y - 18, "ARCHETYPE")
    c.setFont(HEADER_FONT, 22)
    # Wrap the archetype label if it's wider than the box.
    arch_lines = wrap_text(archetype_label, HEADER_FONT, 22, col_w - 28)
    for i, line in enumerate(arch_lines[:2]):
        c.drawString(left_x + 14, y - 44 - i * 26, line)

    # Right: rationale + meta meta meta
    rationale = (design_dna.get("archetype_rationale") or "").strip()
    c.setFillColor(label_grey)
    c.setFont(HEADER_FONT, 9)
    c.drawString(right_x, y - 18, "WHY THIS ARCHETYPE")
    c.setFillColor(body_grey)
    c.setFont(BODY_FONT, 10)
    for i, line in enumerate(wrap_text(rationale, BODY_FONT, 10, col_w)[:4]):
        c.drawString(right_x, y - 36 - i * 14, line)

    # Meta strip below rationale.
    meta_y = y - 96
    metas = [
        ("DENSITY", (design_dna.get("density") or "—").replace("-", " ")),
        ("LAYOUT", (design_dna.get("layout_preference") or "—").replace("-", " ")),
        ("WHITESPACE", (design_dna.get("negative_space") or "—").replace("-", " ")),
    ]
    cell_w = col_w / len(metas)
    for i, (k, v) in enumerate(metas):
        cx = right_x + i * cell_w
        c.setFillColor(label_grey)
        c.setFont(HEADER_FONT, 7)
        c.drawString(cx, meta_y, k)
        c.setFillColor(body_grey)
        c.setFont(HEADER_FONT, 11)
        c.drawString(cx, meta_y - 14, v.title())

    y -= arch_box_h + 36

    # ── Two-column grid: Typography | Photography ─────────────────
    def detail_block(x: float, y_top: float, w: float, title: str, voice: str, sublabel: str, rules: str) -> float:
        c.setFillColor(accent)
        c.rect(x, y_top - 3, 6, 3, fill=1, stroke=0)
        c.setFillColor(black)
        c.setFont(HEADER_FONT, 11)
        c.drawString(x, y_top - 18, title)
        c.setFont(HEADER_FONT, 14)
        c.drawString(x, y_top - 38, voice or "—")
        c.setFillColor(label_grey)
        c.setFont(BODY_FONT, 9)
        c.drawString(x, y_top - 52, sublabel or "")
        c.setFillColor(body_grey)
        c.setFont(BODY_FONT, 10)
        lines = wrap_text(rules or "", BODY_FONT, 10, w)[:4]
        for i, line in enumerate(lines):
            c.drawString(x, y_top - 72 - i * 14, line)
        return y_top - 72 - max(1, len(lines)) * 14

    typo = design_dna.get("typography") or {}
    photo = design_dna.get("photography") or {}
    typo_voice = (typo.get("voice") or "—").title()
    typo_hier = (typo.get("hierarchy") or "—").title()
    photo_treat = (photo.get("treatment") or "—").replace("-", " ").title()
    photo_subj = (photo.get("subject_archetype") or "—").replace("-", " ").title()

    bottom_left = detail_block(
        left_x, y, col_w,
        title="TYPOGRAPHY",
        voice=typo_voice,
        sublabel=f"Hierarchy · {typo_hier}",
        rules=typo.get("rules") or "",
    )
    bottom_right = detail_block(
        right_x, y, col_w,
        title="PHOTOGRAPHY",
        voice=photo_treat,
        sublabel=f"Subject · {photo_subj}",
        rules=photo.get("rules") or "",
    )

    y = min(bottom_left, bottom_right) - 26

    # ── Reference marks row ───────────────────────────────────────
    refs = design_dna.get("reference_marks") or []
    if refs:
        c.setFillColor(label_grey)
        c.setFont(HEADER_FONT, 9)
        c.drawString(MARGIN, y, "REFERENCE MARKS — DESIGN-LANGUAGE NEIGHBOURS")
        y -= 4
        x = MARGIN
        pill_h = 22
        c.setFont(BODY_FONT, 10)
        from reportlab.pdfbase.pdfmetrics import stringWidth
        for ref in refs[:6]:
            w = stringWidth(ref, BODY_FONT, 10) + 18
            if x + w > PAGE_W - MARGIN:
                break
            c.setFillColor(HexColor("#F2F2F2"))
            c.setStrokeColor(HexColor("#E0E0E0"))
            c.setLineWidth(0.5)
            c.roundRect(x, y - pill_h - 6, w, pill_h, 4, fill=1, stroke=1)
            c.setFillColor(black)
            c.drawString(x + 9, y - pill_h + 1, ref)
            x += w + 6
        y -= pill_h + 18

    c.showPage()
    page_used = 1
    next_page = page_num + page_used

    # ── Page 2: Voice-to-design + Do-nots ─────────────────────────
    vmap = design_dna.get("voice_to_design") or {}
    donots = design_dna.get("do_not") or []
    if not vmap and not donots:
        return next_page

    draw_page_chrome(c, "Design DNA", next_page, brand_name)
    y = draw_section_title(
        c,
        "Voice to design",
        "Concrete moves that translate the brand's voice into visual decisions.",
        PAGE_H - MARGIN - 30,
    )

    voice_rows = [
        ("Premium", vmap.get("premium")),
        ("Urgent",  vmap.get("urgent")),
        ("Playful", vmap.get("playful")),
        ("Trust",   vmap.get("trust")),
    ]
    label_w = 110
    for label, rule in voice_rows:
        if not rule:
            continue
        # Pill for the voice tag
        c.setFillColor(accent)
        c.rect(MARGIN, y - 18, label_w, 22, fill=1, stroke=0)
        c.setFillColor(text_on_accent)
        c.setFont(HEADER_FONT, 11)
        c.drawString(MARGIN + 10, y - 12, label.upper())
        # Rule text
        c.setFillColor(body_grey)
        c.setFont(BODY_FONT, 11)
        lines = wrap_text(rule, BODY_FONT, 11, PAGE_W - 2 * MARGIN - label_w - 18)[:3]
        for i, line in enumerate(lines):
            c.drawString(MARGIN + label_w + 18, y - 12 - i * 14, line)
        y -= max(1, len(lines)) * 14 + 18
        if y < MARGIN + 180:
            break

    # Do-nots block
    if donots:
        y -= 14
        c.setFillColor(HexColor("#B91C1C"))
        c.setFont(HEADER_FONT, 11)
        c.drawString(MARGIN, y, "DO NOT")
        y -= 6
        c.setStrokeColor(HexColor("#B91C1C"))
        c.setLineWidth(1.5)
        c.line(MARGIN, y, MARGIN + 60, y)
        y -= 20
        c.setFillColor(body_grey)
        c.setFont(BODY_FONT, 11)
        for entry in donots[:6]:
            text = "× " + entry
            for j, line in enumerate(wrap_text(text, BODY_FONT, 11, PAGE_W - 2 * MARGIN)[:2]):
                c.drawString(MARGIN, y - j * 14, line)
            y -= 14 * max(1, min(2, len(wrap_text(text, BODY_FONT, 11, PAGE_W - 2 * MARGIN)))) + 4
            if y < MARGIN + 60:
                break

    c.showPage()
    return next_page + 1


def voice_page(
    c: canvas.Canvas,
    brand_name: str,
    voice: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Tone-of-voice page: a 1-2 sentence summary at the top, then 3-5
    do/don't pairs in a two-column layout. Returns next page number;
    returns page_num unchanged when no voice data is available."""
    tone = (voice or {}).get("tone_of_voice") or {}
    examples = tone.get("examples") or []
    if not tone.get("summary") and not examples:
        return page_num

    draw_page_chrome(c, "Voice", page_num, brand_name)
    y = draw_section_title(
        c,
        "Tone of voice",
        "How the brand sounds on the page. Use the say / don't-say pairs below as a quick gut-check for any new copy.",
        PAGE_H - MARGIN - 30,
    )
    accent = HexColor(primary_color)

    if tone.get("summary"):
        c.setFillColor(black)
        c.setFont(BODY_FONT, 12)
        for line in wrap_text(tone["summary"], BODY_FONT, 12, PAGE_W - 2 * MARGIN)[:3]:
            c.drawString(MARGIN, y, line)
            y -= 16
        y -= 12

    if examples:
        col_w = (PAGE_W - 2 * MARGIN - GUTTER) / 2
        row_h = 96
        for i, ex in enumerate(examples[:6]):
            row = i // 2
            col = i % 2
            x = MARGIN + col * (col_w + GUTTER)
            cy = y - row * (row_h + 14)
            if cy - row_h < MARGIN + 40:
                break
            context_label = (ex.get("context") or "").strip()
            say = (ex.get("say") or "").strip()
            dont = (ex.get("dont_say") or "").strip()
            # Context tag
            c.setFillColor(accent)
            c.rect(x, cy - 14, 4, 14, fill=1, stroke=0)
            c.setFillColor(HexColor("#666666"))
            c.setFont(HEADER_FONT, 8)
            c.drawString(x + 10, cy - 11, context_label.upper())
            # Say
            c.setFillColor(HexColor("#1A1A1A"))
            c.setFont(HEADER_FONT, 9)
            c.drawString(x, cy - 28, "✓ SAY")
            c.setFillColor(HexColor("#333333"))
            c.setFont(BODY_FONT, 10)
            for j, line in enumerate(wrap_text(say, BODY_FONT, 10, col_w)[:2]):
                c.drawString(x, cy - 42 - j * 12, line)
            # Don't say
            c.setFillColor(HexColor("#B91C1C"))
            c.setFont(HEADER_FONT, 9)
            c.drawString(x, cy - 70, "× DON'T SAY")
            c.setFillColor(HexColor("#7A7A7A"))
            c.setFont(BODY_FONT, 10)
            for j, line in enumerate(wrap_text(dont, BODY_FONT, 10, col_w)[:2]):
                c.drawString(x, cy - 84 - j * 12, line)

    c.showPage()
    return page_num + 1


def voice_spectrum_page(
    c: canvas.Canvas,
    brand_name: str,
    voice: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Voice spectrum: four 1-5 sliders (formal↔casual, serious↔playful,
    premium↔accessible, technical↔plainspoken). Skipped silently if
    the spectrum is missing."""
    spectrum = (voice or {}).get("voice_spectrum") or {}
    rows = [
        ("Formal",     "Casual",        spectrum.get("formal_casual")),
        ("Serious",    "Playful",       spectrum.get("serious_playful")),
        ("Premium",    "Accessible",    spectrum.get("premium_accessible")),
        ("Technical",  "Plainspoken",   spectrum.get("technical_plainspoken")),
    ]
    if not any(v is not None for _, _, v in rows):
        return page_num

    draw_page_chrome(c, "Voice", page_num, brand_name)
    y = draw_section_title(
        c,
        "Voice spectrum",
        "Where the brand sits on four register dimensions. Use these to keep new copy in tune.",
        PAGE_H - MARGIN - 30,
    )

    accent = HexColor(primary_color)
    track_x = MARGIN + 130
    track_w = PAGE_W - MARGIN - track_x - 130
    notch_count = 5
    notch_gap = track_w / (notch_count - 1)

    for left, right, val in rows:
        if val is None:
            continue
        try:
            v = max(1, min(5, int(val)))
        except (TypeError, ValueError):
            continue
        # Left label
        c.setFillColor(HexColor("#1A1A1A"))
        c.setFont(HEADER_FONT, 11)
        c.drawRightString(track_x - 12, y - 4, left)
        # Right label
        c.drawString(track_x + track_w + 12, y - 4, right)
        # Track
        c.setStrokeColor(HexColor("#D1D1D1"))
        c.setLineWidth(1)
        c.line(track_x, y, track_x + track_w, y)
        # Notches
        c.setFillColor(HexColor("#D1D1D1"))
        for i in range(notch_count):
            nx = track_x + i * notch_gap
            c.circle(nx, y, 3, fill=1, stroke=0)
        # Active marker
        ax = track_x + (v - 1) * notch_gap
        c.setFillColor(accent)
        c.circle(ax, y, 8, fill=1, stroke=0)
        c.setFillColor(HexColor(contrasting_text(primary_color)))
        c.setFont(HEADER_FONT, 9)
        c.drawCentredString(ax, y - 3, str(v))
        y -= 56

    notes = spectrum.get("notes")
    if notes:
        y -= 10
        c.setFillColor(HexColor("#666666"))
        c.setFont(BODY_FONT, 11)
        for line in wrap_text(notes, BODY_FONT, 11, PAGE_W - 2 * MARGIN)[:3]:
            c.drawString(MARGIN, y, line)
            y -= 16

    c.showPage()
    return page_num + 1


def messaging_page(
    c: canvas.Canvas,
    brand_name: str,
    voice: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Messaging framework: 10 / 30 / 60 / 150-word elevator pitches +
    tagline candidates. Skipped if all empty."""
    msg = (voice or {}).get("messaging") or {}
    pitches = [
        ("10 WORDS",   msg.get("pitch_10")),
        ("30 WORDS",   msg.get("pitch_30")),
        ("60 WORDS",   msg.get("pitch_60")),
        ("150 WORDS",  msg.get("pitch_150")),
    ]
    taglines = msg.get("tagline_candidates") or []
    if not any(text for _, text in pitches) and not taglines:
        return page_num

    draw_page_chrome(c, "Messaging", page_num, brand_name)
    y = draw_section_title(
        c,
        "Messaging framework",
        "The brand at four sentence lengths — use whichever fits the moment.",
        PAGE_H - MARGIN - 30,
    )

    accent = HexColor(primary_color)
    text_w = PAGE_W - 2 * MARGIN - 90
    label_x = MARGIN

    for label, text in pitches:
        if not text:
            continue
        # Word-count pill
        c.setFillColor(accent)
        c.rect(label_x, y - 14, 84, 18, fill=1, stroke=0)
        c.setFillColor(HexColor(contrasting_text(primary_color)))
        c.setFont(HEADER_FONT, 9)
        c.drawString(label_x + 8, y - 10, label)
        # Pitch text
        c.setFillColor(HexColor("#1A1A1A"))
        c.setFont(BODY_FONT, 11)
        wrapped = wrap_text(text, BODY_FONT, 11, text_w)[:6]
        for i, line in enumerate(wrapped):
            c.drawString(label_x + 100, y - 8 - i * 14, line)
        y -= max(28, len(wrapped) * 14 + 14)
        if y < MARGIN + 120:
            break

    if taglines and y > MARGIN + 90:
        y -= 8
        c.setFillColor(HexColor("#666666"))
        c.setFont(HEADER_FONT, 9)
        c.drawString(MARGIN, y, "TAGLINE CANDIDATES")
        y -= 18
        from reportlab.pdfbase.pdfmetrics import stringWidth
        x = MARGIN
        for tag in taglines[:5]:
            w = stringWidth(tag, HEADER_FONT, 12) + 18
            if x + w > PAGE_W - MARGIN:
                y -= 28
                x = MARGIN
                if y < MARGIN + 40:
                    break
            c.setFillColor(HexColor("#F4F4F4"))
            c.setStrokeColor(HexColor("#D1D1D1"))
            c.setLineWidth(0.5)
            c.roundRect(x, y - 18, w, 24, 4, fill=1, stroke=1)
            c.setFillColor(HexColor("#1A1A1A"))
            c.setFont(HEADER_FONT, 12)
            c.drawString(x + 9, y - 12, tag)
            x += w + 8

    c.showPage()
    return page_num + 1


def personas_page(
    c: canvas.Canvas,
    brand_name: str,
    voice: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Audience personas — card grid (2 per row, max 4). Skipped if no
    personas are present."""
    personas = (voice or {}).get("personas") or []
    if not personas:
        return page_num

    draw_page_chrome(c, "Audience", page_num, brand_name)
    y = draw_section_title(
        c,
        "Audience personas",
        "Who the brand actually talks to. Use these to choose voice + angle when writing new copy.",
        PAGE_H - MARGIN - 30,
    )

    accent = HexColor(primary_color)
    cols = 2
    col_gap = GUTTER
    col_w = (PAGE_W - 2 * MARGIN - col_gap) / cols
    row_pitch = 200

    for i, p in enumerate(personas[:4]):
        row = i // cols
        col = i % cols
        x = MARGIN + col * (col_w + col_gap)
        cy = y - row * row_pitch
        if cy - row_pitch + 20 < MARGIN + 30:
            break
        # Panel
        c.setStrokeColor(HexColor("#E0E0E0"))
        c.setLineWidth(0.5)
        c.rect(x, cy - row_pitch + 20, col_w, row_pitch - 20, fill=0, stroke=1)
        # Header bar
        c.setFillColor(accent)
        c.rect(x, cy - 24, col_w, 24, fill=1, stroke=0)
        c.setFillColor(HexColor(contrasting_text(primary_color)))
        c.setFont(HEADER_FONT, 12)
        c.drawString(x + 12, cy - 17, (p.get("name") or "Persona").upper())

        inner_x = x + 12
        inner_w = col_w - 24
        ty = cy - 40
        c.setFillColor(HexColor("#1A1A1A"))
        c.setFont(BODY_FONT, 10)
        for line in wrap_text(p.get("summary") or "", BODY_FONT, 10, inner_w)[:3]:
            c.drawString(inner_x, ty, line)
            ty -= 13
        ty -= 6

        def list_section(label: str, items: list, color: HexColor, max_items: int) -> float:
            nonlocal ty
            if not items:
                return ty
            c.setFillColor(color)
            c.setFont(HEADER_FONT, 8)
            c.drawString(inner_x, ty, label)
            ty -= 12
            c.setFillColor(HexColor("#333333"))
            c.setFont(BODY_FONT, 9)
            for it in items[:max_items]:
                for j, line in enumerate(wrap_text("· " + str(it), BODY_FONT, 9, inner_w)[:2]):
                    c.drawString(inner_x, ty, line)
                    ty -= 11
            ty -= 4
            return ty

        list_section("NEEDS",       p.get("needs") or [],       HexColor("#0E7490"), 3)
        list_section("OBJECTIONS",  p.get("objections") or [],  HexColor("#B45309"), 2)
        list_section("VOICE CUES",  p.get("voice_cues") or [],  HexColor("#15803D"), 2)

    c.showPage()
    return page_num + 1


def vocabulary_page(
    c: canvas.Canvas,
    brand_name: str,
    voice: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Vocabulary: two columns of pills — preferred (green border) +
    avoid (red border). Skipped if empty."""
    vocab = (voice or {}).get("vocabulary") or {}
    preferred = vocab.get("preferred") or []
    avoid = vocab.get("avoid") or []
    if not preferred and not avoid:
        return page_num

    draw_page_chrome(c, "Voice", page_num, brand_name)
    y = draw_section_title(
        c,
        "Vocabulary",
        "Words the brand uses · words to avoid. Use this as a quick filter when drafting copy.",
        PAGE_H - MARGIN - 30,
    )
    notes = vocab.get("notes")
    if notes:
        c.setFillColor(HexColor("#666666"))
        c.setFont(BODY_FONT, 11)
        for line in wrap_text(notes, BODY_FONT, 11, PAGE_W - 2 * MARGIN)[:2]:
            c.drawString(MARGIN, y, line)
            y -= 14
        y -= 8

    col_gap = GUTTER + 20
    col_w = (PAGE_W - 2 * MARGIN - col_gap) / 2
    left_x = MARGIN
    right_x = MARGIN + col_w + col_gap

    def column(x: float, label: str, items: list, color_hex: str) -> None:
        c.setFillColor(HexColor(color_hex))
        c.setFont(HEADER_FONT, 11)
        c.drawString(x, y, label)
        c.setStrokeColor(HexColor(color_hex))
        c.setLineWidth(1.5)
        c.line(x, y - 6, x + 40, y - 6)

        from reportlab.pdfbase.pdfmetrics import stringWidth
        cy = y - 26
        cx = x
        c.setFont(BODY_FONT, 10)
        for word in items[:14]:
            w = stringWidth(word, BODY_FONT, 10) + 16
            if cx + w > x + col_w:
                cy -= 26
                cx = x
                if cy < MARGIN + 30:
                    break
            c.setFillColor(HexColor("#FAFAFA"))
            c.setStrokeColor(HexColor(color_hex))
            c.setLineWidth(0.6)
            c.roundRect(cx, cy - 16, w, 20, 4, fill=1, stroke=1)
            c.setFillColor(HexColor("#1A1A1A"))
            c.drawString(cx + 8, cy - 11, word)
            cx += w + 6

    column(left_x,  "PREFERRED", preferred, "#15803D")
    column(right_x, "AVOID",     avoid,     "#B91C1C")

    c.showPage()
    return page_num + 1


def photography_dos_donts_page(
    c: canvas.Canvas,
    brand_name: str,
    images: dict,
    design_dna: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Photography dos/don'ts: the top suitable_for_ads photo from the
    brand's marketing imagery on the left, the design_dna.do_not bullets
    on the right. Skipped if either source is empty."""
    marketing = (images or {}).get("marketing_imagery") or []
    donots = (design_dna or {}).get("do_not") or []
    if not marketing and not donots:
        return page_num

    draw_page_chrome(c, "Photography", page_num, brand_name)
    y = draw_section_title(
        c,
        "Photography do · don't",
        "Use real photographs that fit the brand's design DNA. Avoid the patterns on the right.",
        PAGE_H - MARGIN - 30,
    )

    col_w = (PAGE_W - 2 * MARGIN - GUTTER) / 2
    left_x = MARGIN
    right_x = MARGIN + col_w + GUTTER

    # DO panel — biggest suitable photo
    c.setStrokeColor(HexColor("#15803D"))
    c.setLineWidth(0.8)
    image_h = 240
    c.rect(left_x, y - image_h, col_w, image_h, fill=0, stroke=1)
    c.setFillColor(HexColor("#15803D"))
    c.setFont(HEADER_FONT, 11)
    c.drawString(left_x, y + 6, "✓ DO")
    pick = next((m for m in marketing if m.get("url")), None)
    if pick:
        data = fetch_image(pick.get("url") or "")
        if data:
            try:
                img = ImageReader(io.BytesIO(data))
                iw, ih = img.getSize()
                scale = min(col_w / iw, image_h / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(
                    img,
                    left_x + (col_w - dw) / 2,
                    y - image_h + (image_h - dh) / 2,
                    dw, dh, mask="auto",
                )
            except Exception as e:
                print(f"  ! could not render do/dont photo: {e}", file=sys.stderr)
        cap_y = y - image_h - 14
        c.setFillColor(HexColor("#333333"))
        c.setFont(BODY_FONT, 9)
        for line in wrap_text(pick.get("description") or "", BODY_FONT, 9, col_w)[:3]:
            c.drawString(left_x, cap_y, line)
            cap_y -= 11

    # DON'T panel — bullet list
    c.setStrokeColor(HexColor("#B91C1C"))
    c.setLineWidth(0.8)
    c.rect(right_x, y - image_h, col_w, image_h, fill=0, stroke=1)
    c.setFillColor(HexColor("#B91C1C"))
    c.setFont(HEADER_FONT, 11)
    c.drawString(right_x, y + 6, "× DON'T")
    ty = y - 24
    c.setFillColor(HexColor("#333333"))
    c.setFont(BODY_FONT, 11)
    for bullet in donots[:6]:
        for j, line in enumerate(wrap_text("× " + str(bullet), BODY_FONT, 11, col_w - 24)[:3]):
            c.drawString(right_x + 14, ty - j * 14, line)
        ty -= 14 * max(1, min(3, len(wrap_text("× " + str(bullet), BODY_FONT, 11, col_w - 24)))) + 8
        if ty < y - image_h + 14:
            break

    c.showPage()
    return page_num + 1


def ui_components_page(
    c: canvas.Canvas,
    brand_name: str,
    brand: dict,
    typography: dict,
    page_num: int,
) -> int:
    """A 'design system' page: buttons, badges/pills, a card, form
    inputs, alert states — all rendered in brand colours."""
    primary = brand.get("primary_color") or "#111111"
    secondary = brand.get("secondary_color") or "#666666"
    accent = brand.get("accent_color") or primary
    text_color = brand.get("text_color") or "#111111"
    primary_font = typography.get("primary_font") or HEADER_FONT
    body_font = typography.get("secondary_font") or BODY_FONT
    # ReportLab can't render arbitrary downloaded fonts; fall back to
    # built-in faces. Use the brand name as a label only.
    of_primary = HEADER_FONT
    of_body = BODY_FONT

    draw_page_chrome(c, "Components", page_num, brand_name)
    y = draw_section_title(
        c,
        "UI components",
        "Reference treatment for buttons, badges, cards, form fields and alerts in the brand palette.",
        PAGE_H - MARGIN - 30,
    )

    accent_col = HexColor(primary)
    text_on_accent = HexColor(contrasting_text(primary))
    from reportlab.pdfbase.pdfmetrics import stringWidth

    # ── Buttons row ──
    c.setFillColor(HexColor("#666666"))
    c.setFont(of_primary, 9)
    c.drawString(MARGIN, y, "BUTTONS")
    by = y - 26
    bx = MARGIN
    def button(label: str, fill: str, fg: str, border: str | None = None) -> None:
        nonlocal bx
        w = stringWidth(label, of_primary, 12) + 36
        if fill:
            c.setFillColor(HexColor(fill))
            c.rect(bx, by - 22, w, 32, fill=1, stroke=0)
        if border:
            c.setStrokeColor(HexColor(border))
            c.setLineWidth(1)
            c.rect(bx, by - 22, w, 32, fill=0, stroke=1)
        c.setFillColor(HexColor(fg))
        c.setFont(of_primary, 12)
        c.drawString(bx + 18, by - 13, label)
        bx += w + 14

    button("Primary action", primary, contrasting_text(primary))
    button("Secondary", "#FFFFFF", text_color, border="#D1D1D1")
    button("Accent", accent, contrasting_text(accent))

    y = by - 40

    # ── Pills / badges ──
    c.setFillColor(HexColor("#666666"))
    c.setFont(of_primary, 9)
    c.drawString(MARGIN, y, "BADGES")
    py = y - 22
    px = MARGIN
    def pill(label: str, fill: str, fg: str) -> None:
        nonlocal px
        w = stringWidth(label, of_primary, 9) + 18
        c.setFillColor(HexColor(fill))
        c.roundRect(px, py - 14, w, 18, 9, fill=1, stroke=0)
        c.setFillColor(HexColor(fg))
        c.setFont(of_primary, 9)
        c.drawString(px + 9, py - 10, label)
        px += w + 8

    pill("NEW", primary, contrasting_text(primary))
    pill("FEATURED", secondary, contrasting_text(secondary))
    pill("LIMITED", accent, contrasting_text(accent))
    pill("LIVE", "#15803D", "#FFFFFF")
    pill("DRAFT", "#6B7280", "#FFFFFF")
    y = py - 36

    # ── Card sample ──
    c.setFillColor(HexColor("#666666"))
    c.setFont(of_primary, 9)
    c.drawString(MARGIN, y, "CARD")
    cy_top = y - 8
    card_w = (PAGE_W - 2 * MARGIN - GUTTER) / 2
    card_h = 110
    c.setStrokeColor(HexColor("#E0E0E0"))
    c.setLineWidth(0.5)
    c.rect(MARGIN, cy_top - card_h, card_w, card_h, fill=0, stroke=1)
    # Accent strip
    c.setFillColor(accent_col)
    c.rect(MARGIN, cy_top - 4, card_w, 4, fill=1, stroke=0)
    # Title
    c.setFillColor(HexColor(text_color))
    c.setFont(of_primary, 14)
    c.drawString(MARGIN + 14, cy_top - 26, "Card title")
    c.setFillColor(HexColor("#666666"))
    c.setFont(of_body, 10)
    c.drawString(MARGIN + 14, cy_top - 42, "Short supporting line.")
    # Mini button on the card
    btn_label = "Action"
    btn_w = stringWidth(btn_label, of_primary, 10) + 22
    c.setFillColor(accent_col)
    c.rect(MARGIN + 14, cy_top - card_h + 16, btn_w, 22, fill=1, stroke=0)
    c.setFillColor(text_on_accent)
    c.setFont(of_primary, 10)
    c.drawString(MARGIN + 25, cy_top - card_h + 22, btn_label)

    # ── Form input sample ──
    fx = MARGIN + card_w + GUTTER
    c.setFillColor(HexColor("#666666"))
    c.setFont(of_primary, 9)
    c.drawString(fx, y, "FORM")
    iy = cy_top - 24
    c.setFillColor(HexColor("#333333"))
    c.setFont(of_primary, 9)
    c.drawString(fx, iy, "EMAIL")
    c.setStrokeColor(HexColor("#D1D1D1"))
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(fx, iy - 30, card_w, 28, fill=1, stroke=1)
    c.setFillColor(HexColor("#9CA3AF"))
    c.setFont(of_body, 11)
    c.drawString(fx + 10, iy - 22, "you@example.com")
    # Submit
    iy -= 50
    c.setFillColor(accent_col)
    c.rect(fx, iy - 26, 130, 28, fill=1, stroke=0)
    c.setFillColor(text_on_accent)
    c.setFont(of_primary, 11)
    c.drawString(fx + 20, iy - 17, "Subscribe")

    y = cy_top - card_h - 24

    # ── Alerts ──
    c.setFillColor(HexColor("#666666"))
    c.setFont(of_primary, 9)
    c.drawString(MARGIN, y, "ALERTS")
    ay = y - 24
    alert_w = (PAGE_W - 2 * MARGIN - GUTTER * 2) / 3
    alerts = [
        ("Success",  "Saved.",                "#15803D"),
        ("Info",     "Heads up — check this.", primary),
        ("Error",    "Something went wrong.", "#B91C1C"),
    ]
    for i, (tag, msg, color) in enumerate(alerts):
        ax = MARGIN + i * (alert_w + GUTTER)
        c.setStrokeColor(HexColor(color))
        c.setLineWidth(0.8)
        c.rect(ax, ay - 44, alert_w, 44, fill=0, stroke=1)
        c.setFillColor(HexColor(color))
        c.rect(ax, ay - 44, 4, 44, fill=1, stroke=0)
        c.setFillColor(HexColor(color))
        c.setFont(of_primary, 10)
        c.drawString(ax + 12, ay - 14, tag.upper())
        c.setFillColor(HexColor("#1A1A1A"))
        c.setFont(of_body, 10)
        for j, line in enumerate(wrap_text(msg, of_body, 10, alert_w - 16)[:2]):
            c.drawString(ax + 12, ay - 28 - j * 12, line)

    # Silence unused-locals lint — these were captured from the
    # brand/typography for future use (custom-font swap-in).
    _ = (primary_font, body_font)
    c.showPage()
    return page_num + 1


def typography_page(c: canvas.Canvas, brand_name: str, typography: dict, page_num: int) -> None:
    draw_page_chrome(c, "Typography", page_num, brand_name)
    y = draw_section_title(c, "Typography", "Display typeface and type scale.", PAGE_H - MARGIN - 30)

    primary_font = typography.get("primary_font") or "Helvetica"
    secondary_font = typography.get("secondary_font") or "Helvetica"

    c.setFillColor(black)
    c.setFont(HEADER_FONT, 14)
    c.drawString(MARGIN, y, "DISPLAY TYPEFACE")
    y -= 24
    c.setFont(HEADER_FONT, 64)
    c.drawString(MARGIN, y - 50, "Aa")
    c.setFont(BODY_FONT, 22)
    c.drawString(MARGIN + 110, y - 10, primary_font)
    c.setFont(BODY_FONT, 10)
    c.setFillColor(HexColor("#666666"))
    c.drawString(MARGIN + 110, y - 28, "Detected on heading selectors")
    c.drawString(MARGIN + 110, y - 42, "AaBbCcDdEeFfGg  1234567890  !@#$%&")

    y -= 100
    c.setFillColor(black)
    c.setFont(HEADER_FONT, 14)
    c.drawString(MARGIN, y, "BODY TYPEFACE")
    y -= 18
    c.setFont(BODY_FONT, 14)
    c.drawString(MARGIN, y, secondary_font)

    y -= 40
    c.setFont(HEADER_FONT, 14)
    c.drawString(MARGIN, y, "TYPE SCALE")
    y -= 8
    scale = [
        ("DISPLAY", 48, "Where headlines feel powerful"),
        ("H1", 40, "Shaping the brand voice"),
        ("H2", 32, "Section titles & key callouts"),
        ("H3", 24, "Subheads and feature copy"),
        ("Body", 16, "The everyday paragraph weight your readers will spend the most time with."),
        ("Caption", 12, "Small notes, metadata, footnotes."),
    ]
    for level, size, example in scale:
        y -= max(size, 22) + 6
        c.setFont(BODY_FONT, 9)
        c.setFillColor(HexColor("#666666"))
        c.drawString(MARGIN, y + size - 4, f"{level} · {size}px")
        c.setFillColor(black)
        c.setFont(BODY_FONT, size)
        c.drawString(MARGIN + 90, y, example)
    c.showPage()


def _image_luminance_profile(data: bytes) -> tuple[float, float]:
    """Return (mean_luma, white_pixel_fraction) of the OPAQUE pixels of an
    image, both on a 0..255 / 0..1 scale. Used to decide what tile colour
    a logo or favicon should sit on so it doesn't disappear into the page.

    Skips transparent pixels (alpha < 32) — a logo with a white wordmark
    on a transparent background should be treated as "white", not "the
    average of nothing".
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGBA")
            # Sample a fixed thumbnail — full-size logos can be 1000x1000+
            # and we don't need pixel accuracy for this heuristic.
            im.thumbnail((128, 128))
            pixels = list(im.getdata())
    except Exception:
        return (255.0, 1.0)  # treat unreadable as "white" -> dark tile

    opaque = [(r, g, b) for (r, g, b, a) in pixels if a >= 32]
    if not opaque:
        return (255.0, 1.0)
    total = 0.0
    near_white = 0
    for r, g, b in opaque:
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        total += luma
        if luma >= 240:
            near_white += 1
    mean = total / len(opaque)
    frac = near_white / len(opaque)
    return mean, frac


def _is_light_artwork(data: bytes) -> bool:
    """True if the image is predominantly white/very light — i.e. a logo
    designed for a dark backdrop. Such artwork is invisible on the
    default white PDF page and needs a contrasting tile."""
    mean, frac_white = _image_luminance_profile(data)
    # Either the average opaque pixel is very light, or more than half
    # the opaque pixels are essentially white.
    return mean >= 220 or frac_white >= 0.5


def _pick_contrasting_bg(data: bytes | None, dark_hex: str) -> str:
    """White by default. If the artwork would vanish on white, swap to a
    dark backdrop (the brand primary, or a neutral dark if no primary)."""
    if not data:
        return "#FFFFFF"
    return dark_hex if _is_light_artwork(data) else "#FFFFFF"


def _draw_logo_in_tile(
    c: canvas.Canvas,
    data: bytes | None,
    url: str,
    x: float,
    y_top: float,
    w: float,
    h: float,
    bg_hex: str,
    border: bool = False,
) -> None:
    """Render a logo image centred in a tile of the given background colour.
    `y_top` is the top edge of the tile."""
    c.setFillColor(HexColor(bg_hex))
    c.rect(x, y_top - h, w, h, fill=1, stroke=0)
    if border:
        c.setStrokeColor(HexColor("#E0E0E0"))
        c.setLineWidth(0.5)
        c.rect(x, y_top - h, w, h, fill=0, stroke=1)
    if not data:
        return
    try:
        img = ImageReader(io.BytesIO(data))
        iw, ih = img.getSize()
        scale = min((w - 24) / iw, (h - 24) / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(
            img,
            x + (w - dw) / 2,
            y_top - h + (h - dh) / 2,
            dw, dh, mask="auto",
        )
    except Exception as e:
        print(f"  ! could not render {url}: {e}", file=sys.stderr)


def logos_pages(
    c: canvas.Canvas,
    brand_name: str,
    images: dict,
    start_url: str,
    start_page: int,
    primary_color: str = "#111111",
) -> int:
    """Brand-guidelines convention: each primary logo shown on white, on the
    brand colour, and on black so designers can verify legibility everywhere
    the mark needs to live."""
    page = start_page
    candidates = pick_logo_candidates(images, start_url)
    draw_page_chrome(c, "Logos & Marks", page, brand_name)
    y = draw_section_title(
        c,
        "Primary Mark",
        "The brand's primary logo. Use this in collateral, signage, and digital.",
        PAGE_H - MARGIN - 30,
    )

    if not candidates:
        c.setFont(BODY_FONT, 11)
        c.setFillColor(HexColor("#666666"))
        c.drawString(MARGIN, y, "No brand_primary logo detected in the YAML.")
        c.showPage()
        return page + 1

    from reportlab.pdfbase.pdfmetrics import stringWidth

    url = candidates[0]
    data = fetch_image(url)

    # Brand-guidelines convention: every primary mark is shown on both
    # light and dark backdrops so designers can see legibility on each.
    # If the artwork is itself light (white logo) we'd otherwise render
    # an invisible tile on white — flip the layout so the dark tile is
    # prominent and the light tile is the smaller secondary swatch.
    dark_hex = primary_color if primary_color and primary_color.upper() != "#FFFFFF" else "#111111"
    light_is_dominant = data is not None and _is_light_artwork(data)

    full_w = PAGE_W - 2 * MARGIN

    # Vertical budget on landscape A4: y is the top of the primary
    # tile; below it we render:
    #   primary tile (primary_h)
    #   12  gap to primary label
    #   10  primary label
    #   16  gap
    #   companion_h (90) companion tile
    #   12  gap to companion label
    #   10  companion label / filename row
    # Footer band sits ~40pt above page bottom — reserve MARGIN + 40
    # below the last text row.
    companion_h = 90
    footer_band = 40
    reserved_below_primary = (
        12 + 10 + 16 + companion_h + 12 + 10 + footer_band
    )
    # Cap at 240pt so the primary tile never dominates the page even on
    # very tall headers.
    primary_h = max(120, min(240, y - MARGIN - reserved_below_primary))
    if light_is_dominant:
        # Dark backdrop primary; small white companion below.
        _draw_logo_in_tile(c, data, url, MARGIN, y, full_w, primary_h, dark_hex, border=False)
        primary_label = f"On brand colour ({dark_hex})"
        secondary_bg = "#FFFFFF"
        secondary_label = "On white (mark may appear faint)"
    else:
        _draw_logo_in_tile(c, data, url, MARGIN, y, full_w, primary_h, "#FFFFFF", border=True)
        primary_label = "On white"
        secondary_bg = dark_hex
        secondary_label = f"On brand colour ({dark_hex})"

    c.setFillColor(HexColor("#666666"))
    c.setFont(BODY_FONT, 8)
    c.drawString(MARGIN, y - primary_h - 12, primary_label)

    # Smaller companion tile underneath (companion_h defined above).
    companion_y = y - primary_h - 28
    _draw_logo_in_tile(
        c, data, url, MARGIN, companion_y, full_w, companion_h, secondary_bg,
        border=(secondary_bg == "#FFFFFF"),
    )
    c.setFillColor(HexColor("#666666"))
    c.setFont(BODY_FONT, 8)
    c.drawString(MARGIN, companion_y - companion_h - 12, secondary_label)

    # Filename anchored to the bottom of the section.
    basename = url.rsplit("/", 1)[-1] or url
    while basename and stringWidth(basename, BODY_FONT, 8) > full_w:
        basename = basename[:-1]
        if basename and stringWidth(basename + "…", BODY_FONT, 8) <= full_w:
            basename += "…"
            break
    c.setFillColor(HexColor("#999999"))
    c.setFont(BODY_FONT, 7)
    c.drawRightString(MARGIN + full_w, companion_y - companion_h - 12, basename)

    c.showPage()
    return page + 1


def pick_logo_candidates(images: dict, start_url: str) -> list[str]:
    domain = urlparse(start_url).netloc.lower()
    # Prefer Bedrock-classified brand_primary; fall back to legacy "logo" if the
    # Bedrock assets pass didn't run.
    imlist = images.get("images", [])
    logos = [im for im in imlist if im.get("role") == "brand_primary"]
    if not logos:
        logos = [im for im in imlist if im.get("role") == "logo"]

    def score(im: dict) -> tuple[int, int]:
        url = (im.get("url") or "").lower()
        same_domain = domain in url
        # heuristic: own-domain + filename literally contains "logo" beats partner badges
        name_score = 0
        if "/logo." in url or url.endswith("/logo.png") or url.endswith("/logo.jpg"):
            name_score = 3
        elif "logo" in url.rsplit("/", 1)[-1]:
            name_score = 1
        return (int(same_domain) * 2 + name_score, -len(url))

    logos.sort(key=score, reverse=True)
    seen = set()
    out: list[str] = []
    for im in logos:
        u = im.get("url")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def mission_page(
    c: canvas.Canvas,
    brand_name: str,
    essence: dict,
    brand: dict,
    page_num: int,
) -> int:
    """Big quote-style mission statement on the brand's primary colour."""
    mission = (essence or {}).get("mission_statement") or ""
    if not mission:
        return page_num
    primary = brand.get("primary_color") or "#111111"
    text_color = contrasting_text(primary)

    c.setFillColor(HexColor(primary))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(HexColor(text_color))

    # Eyebrow
    c.setFont(BODY_FONT, 10)
    c.drawString(MARGIN, PAGE_H - MARGIN, f"{brand_name.upper()}  ·  MISSION")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN, f"{page_num:03d}")

    # Quote mark
    c.setFont(HEADER_FONT, 96)
    c.drawString(MARGIN, PAGE_H - MARGIN - 70, "“")

    # Mission text — wrap large
    size = 32
    max_width = PAGE_W - 2 * MARGIN - 40
    lines = wrap_text(mission, HEADER_FONT, size, max_width)
    while len(lines) > 5 and size > 18:
        size -= 2
        lines = wrap_text(mission, HEADER_FONT, size, max_width)
    c.setFont(HEADER_FONT, size)
    y = PAGE_H / 2 + (len(lines) * size * 1.15) / 2
    for line in lines:
        c.drawString(MARGIN + 20, y, line)
        y -= size * 1.15

    # Tone-of-voice strip at the bottom (optional)
    tov = (essence or {}).get("tone_of_voice")
    if tov:
        c.setFont(BODY_FONT, 10)
        for i, line in enumerate(wrap_text(f"Tone of voice — {tov}", BODY_FONT, 10, PAGE_W - 2 * MARGIN)):
            c.drawString(MARGIN, MARGIN + 30 - i * 14, line)

    # Consultancy logo bottom-right (dark page)
    draw_consultancy_footer_logo(
        c, DEFAULT_CONSULTANCY_LOGO_URL, DEFAULT_CONSULTANCY_NAME,
        on_dark=(text_color == "#FFFFFF"),
    )

    c.showPage()
    return page_num + 1


def core_services_page(
    c: canvas.Canvas,
    brand_name: str,
    essence: dict,
    brand: dict,
    page_num: int,
) -> int:
    services = (essence or {}).get("core_services") or []
    if not services:
        return page_num
    draw_page_chrome(c, "Core Services", page_num, brand_name)
    y = draw_section_title(
        c,
        "Core Services",
        "The pillars the brand sells against — derived from the company's own pages.",
        PAGE_H - MARGIN - 30,
    )

    primary = brand.get("primary_color") or "#111111"
    accent_text = contrasting_text(primary)
    # 3-up grid, two rows max — clip if more.
    cols = 3
    visible = services[:6]
    rows = (len(visible) + cols - 1) // cols
    gap = GUTTER
    cell_w = (PAGE_W - 2 * MARGIN - gap * (cols - 1)) / cols
    cell_h = min(180, (y - MARGIN - 30) / max(rows, 1) - gap)

    for i, svc in enumerate(visible):
        row, col = divmod(i, cols)
        x = MARGIN + col * (cell_w + gap)
        cy = y - row * (cell_h + gap)
        # Colored ribbon at the top of each tile
        ribbon_h = 32
        c.setFillColor(HexColor(primary))
        c.rect(x, cy - ribbon_h, cell_w, ribbon_h, fill=1, stroke=0)
        c.setFillColor(HexColor(accent_text))
        c.setFont(HEADER_FONT, 12)
        name = (svc.get("name") or "").upper()
        # Crop to one line
        while name and len(name) > 0 and ImageReader is not None:
            from reportlab.pdfbase.pdfmetrics import stringWidth
            if stringWidth(name, HEADER_FONT, 12) <= cell_w - 20:
                break
            name = name[:-1]
        c.drawString(x + 10, cy - 20, name)

        # Body panel
        c.setFillColor(HexColor("#F4F4F4"))
        c.rect(x, cy - cell_h, cell_w, cell_h - ribbon_h, fill=1, stroke=0)
        c.setFillColor(black)
        c.setFont(BODY_FONT, 10)
        desc = svc.get("description") or ""
        text = c.beginText(x + 10, cy - ribbon_h - 18)
        text.setLeading(14)
        for line in wrap_text(desc, BODY_FONT, 10, cell_w - 20)[:6]:
            text.textLine(line)
        c.drawText(text)

    c.showPage()
    return page_num + 1


def strengths_page(
    c: canvas.Canvas,
    brand_name: str,
    essence: dict,
    brand: dict,
    page_num: int,
) -> int:
    strengths = (essence or {}).get("key_strengths") or []
    propositions = (essence or {}).get("value_propositions") or []
    if not strengths and not propositions:
        return page_num
    draw_page_chrome(c, "What We Stand For", page_num, brand_name)
    y = draw_section_title(
        c,
        "What We Stand For",
        "Strengths and value propositions the brand emphasises — quote these in copy.",
        PAGE_H - MARGIN - 30,
    )

    primary = brand.get("primary_color") or "#111111"

    if propositions:
        c.setFillColor(black)
        c.setFont(HEADER_FONT, 14)
        c.drawString(MARGIN, y, "VALUE PROPOSITIONS")
        y -= 18
        chip_h = 32
        chip_gap = 10
        x = MARGIN
        c.setFont(BODY_FONT, 11)
        from reportlab.pdfbase.pdfmetrics import stringWidth
        for vp in propositions[:6]:
            w = stringWidth(vp, BODY_FONT, 11) + 28
            if x + w > PAGE_W - MARGIN:
                x = MARGIN
                y -= chip_h + chip_gap
            c.setFillColor(HexColor(primary))
            c.rect(x, y - chip_h + 6, w, chip_h, fill=1, stroke=0)
            c.setFillColor(HexColor(contrasting_text(primary)))
            c.drawString(x + 14, y - chip_h + 18, vp)
            c.setFont(BODY_FONT, 11)
            x += w + chip_gap
        y -= chip_h + 24

    if strengths:
        c.setFillColor(black)
        c.setFont(HEADER_FONT, 14)
        c.drawString(MARGIN, y, "KEY STRENGTHS")
        y -= 20
        c.setFont(BODY_FONT, 13)
        for s in strengths[:8]:
            # bullet rule in primary, then text
            c.setFillColor(HexColor(primary))
            c.rect(MARGIN, y - 4, 8, 14, fill=1, stroke=0)
            c.setFillColor(black)
            for i, line in enumerate(wrap_text(s, BODY_FONT, 13, PAGE_W - 2 * MARGIN - 22)):
                c.drawString(MARGIN + 18, y - i * 16, line)
            y -= 16 * max(1, len(wrap_text(s, BODY_FONT, 13, PAGE_W - 2 * MARGIN - 22))) + 6
            if y < MARGIN + 40:
                break

    c.showPage()
    return page_num + 1


def supporting_marks_page(
    c: canvas.Canvas,
    brand_name: str,
    images: dict,
    page_num: int,
) -> int:
    """Trust marks, badges, accreditations — Bedrock-tagged as brand_supporting."""
    supporting = [im for im in images.get("images", []) if im.get("role") == "brand_supporting"]
    if not supporting:
        return page_num
    draw_page_chrome(c, "Trust Marks", page_num, brand_name)
    y = draw_section_title(
        c,
        "Trust Marks & Supporting Assets",
        "Badges, accreditations and supporting brand marks. Use alongside the primary mark in collateral.",
        PAGE_H - MARGIN - 30,
    )

    cols = 3
    cell_w = (PAGE_W - 2 * MARGIN - GUTTER * (cols - 1)) / cols
    cell_h = 200
    # Neutral dark backdrop for any asset that would vanish on white.
    # Supporting marks come from many sources and rarely match the brand
    # colour, so a neutral charcoal reads cleaner than the primary.
    dark_hex = "#111111"
    for i, im in enumerate(supporting[:6]):
        row, col = divmod(i, cols)
        x = MARGIN + col * (cell_w + GUTTER)
        cy = y - row * (cell_h + 40)
        data = fetch_image(im.get("url") or "")
        # Per-cell backdrop: white for normal artwork, brand colour for
        # marks that would otherwise vanish on a white page.
        bg_hex = _pick_contrasting_bg(data, dark_hex)
        on_white = bg_hex == "#FFFFFF"
        c.setFillColor(HexColor(bg_hex))
        c.rect(x, cy - cell_h, cell_w, cell_h, fill=1, stroke=0)
        if on_white:
            c.setStrokeColor(HexColor("#E0E0E0"))
            c.setLineWidth(0.5)
            c.rect(x, cy - cell_h, cell_w, cell_h, fill=0, stroke=1)
        if data:
            try:
                img = ImageReader(io.BytesIO(data))
                iw, ih = img.getSize()
                scale = min((cell_w - 24) / iw, (cell_h - 24) / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(
                    img,
                    x + (cell_w - dw) / 2,
                    cy - cell_h + (cell_h - dh) / 2,
                    dw, dh, mask="auto",
                )
            except Exception as e:
                print(f"  ! could not render supporting mark {im.get('url')}: {e}", file=sys.stderr)
        # caption: Bedrock description + truncated URL
        c.setFillColor(black)
        c.setFont(BODY_FONT, 9)
        desc = im.get("bedrock_description") or ""
        for j, line in enumerate(wrap_text(desc, BODY_FONT, 9, cell_w)[:2]):
            c.drawString(x, cy - cell_h - 12 - j * 12, line)
    c.showPage()
    return page_num + 1


def contact_page(
    c: canvas.Canvas,
    brand_name: str,
    essence: dict,
    brand: dict,
    page_num: int,
) -> int:
    contact = (essence or {}).get("contact_details") or {}
    has_any = any(contact.get(k) for k in ("phone", "email", "address", "hours")) \
              or (contact.get("social_links") or [])
    if not has_any:
        return page_num
    draw_page_chrome(c, "Contact", page_num, brand_name)
    y = draw_section_title(
        c,
        "Contact",
        "How customers reach the business — pulled verbatim from the website copy.",
        PAGE_H - MARGIN - 30,
    )

    primary = brand.get("primary_color") or "#111111"
    label_w = 100
    rows = [
        ("Phone",   contact.get("phone")),
        ("Email",   contact.get("email")),
        ("Address", contact.get("address")),
        ("Hours",   contact.get("hours")),
    ]
    c.setFont(BODY_FONT, 13)
    for label, value in rows:
        if not value:
            continue
        # Coloured pill for the label
        c.setFillColor(HexColor(primary))
        c.rect(MARGIN, y - 22, label_w, 26, fill=1, stroke=0)
        c.setFillColor(HexColor(contrasting_text(primary)))
        c.setFont(HEADER_FONT, 11)
        c.drawString(MARGIN + 12, y - 14, label.upper())
        # Value to the right
        c.setFillColor(black)
        c.setFont(BODY_FONT, 13)
        for i, line in enumerate(wrap_text(str(value), BODY_FONT, 13,
                                           PAGE_W - 2 * MARGIN - label_w - 20)):
            c.drawString(MARGIN + label_w + 16, y - 14 - i * 16, line)
        y -= 26 + 14

    social = contact.get("social_links") or []
    if social:
        y -= 10
        c.setFillColor(HexColor("#666666"))
        c.setFont(HEADER_FONT, 11)
        c.drawString(MARGIN, y, "SOCIAL")
        y -= 18
        c.setFillColor(black)
        c.setFont(BODY_FONT, 11)
        for link in social[:8]:
            c.drawString(MARGIN, y, link)
            y -= 16

    c.showPage()
    return page_num + 1


def consultancy_credits_page(
    c: canvas.Canvas,
    brand_name: str,
    consultancy_name: str,
    consultancy_url: str,
    consultancy_logo_url: str | None,
    consultancy_tagline: str,
    page_num: int,
) -> int:
    """Closing page — consultancy branding (Andrew Rea Associates by default).
    Uses neutral dark background so the consultancy mark doesn't fight with
    whatever client brand we just rendered for."""
    bg = "#111111"
    c.setFillColor(HexColor(bg))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(white)

    # Eyebrow + page number
    c.setFont(BODY_FONT, 8)
    c.drawString(MARGIN, PAGE_H - MARGIN + 14, "CREDITS")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 14,
                      f"{brand_name} · Brand Guidelines")
    c.drawString(MARGIN, MARGIN - 18, f"{page_num:03d}")

    # Consultancy logo
    if consultancy_logo_url:
        data = fetch_image(consultancy_logo_url)
        if data:
            try:
                img = ImageReader(io.BytesIO(data))
                iw, ih = img.getSize()
                max_w, max_h = 280, 120
                scale = min(max_w / iw, max_h / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(
                    img, MARGIN, PAGE_H - MARGIN - dh,
                    dw, dh, mask="auto",
                )
            except Exception as e:
                print(f"  ! could not render consultancy logo: {e}", file=sys.stderr)

    # Body
    c.setFillColor(white)
    c.setFont(HEADER_FONT, 36)
    c.drawString(MARGIN, PAGE_H / 2 + 20, "Prepared by")
    c.setFont(HEADER_FONT, 36)
    c.drawString(MARGIN, PAGE_H / 2 - 22, consultancy_name)

    c.setFont(BODY_FONT, 14)
    c.setFillColor(HexColor("#bbbbbb"))
    text = c.beginText(MARGIN, PAGE_H / 2 - 60)
    text.setLeading(18)
    for line in wrap_text(consultancy_tagline, BODY_FONT, 14, PAGE_W - 2 * MARGIN):
        text.textLine(line)
    c.drawText(text)

    # URL at the bottom
    c.setFillColor(white)
    c.setFont(BODY_FONT, 14)
    c.drawString(MARGIN, MARGIN + 40, consultancy_url)

    c.showPage()
    return page_num + 1


def photography_page(
    c: canvas.Canvas,
    brand_name: str,
    images: dict,
    page_num: int,
    primary_color: str = "#111111",
) -> int:
    """Render the brand's marketing imagery across as many slides as
    needed — one centred row of up to 3 large images per slide, each
    captioned with a category pill + description.

    Cells are sized to fill the available vertical budget so the
    photos read large; we just add more slides rather than shrinking.
    Returns the next page number. If no marketing imagery was
    classified, returns page_num unchanged."""
    marketing = (images or {}).get("marketing_imagery") or []
    if not marketing:
        return page_num

    from reportlab.pdfbase.pdfmetrics import stringWidth

    # Sort: lifestyle/product/context first (most useful for ads), then
    # team/testimonial/etc. Cap at 12 photos = max 4 photography slides
    # so the brand book doesn't bloat for image-heavy sites.
    category_order = {
        "lifestyle": 0, "product": 1, "context": 2,
        "team": 3, "testimonial": 4, "decorative": 5, "other": 6,
    }
    items = sorted(
        marketing,
        key=lambda it: category_order.get(it.get("category") or "other", 9),
    )[:12]

    cols = 3
    cell_w = (PAGE_W - 2 * MARGIN - GUTTER * (cols - 1)) / cols

    # Caption layout (per cell, below the image).
    pill_h = 14
    desc_lines = 3
    desc_line_h = 11
    caption_block = 10 + pill_h + 6 + desc_lines * desc_line_h
    footer_band = 50  # safe space above the page-chrome footer
    image_caption_gap = 10

    # Paginate: 3 photos per slide.
    pages_used = 0
    for page_start in range(0, len(items), cols):
        slice_items = items[page_start : page_start + cols]
        n = len(slice_items)

        total_slides = (len(items) + cols - 1) // cols
        draw_page_chrome(c, "Photography", page_num + pages_used, brand_name)
        y = draw_section_title(
            c,
            (
                f"Brand Photography ({pages_used + 1} of {total_slides})"
                if total_slides > 1 else "Brand Photography"
            ),
            "Real photography pulled from the site, categorised so designers "
            "and the ad generator can pick the right shot for each campaign.",
            PAGE_H - MARGIN - 30,
        )

        # All remaining vertical space goes to the image cell (caption
        # block reserved beneath).
        cell_h = y - MARGIN - footer_band - caption_block - image_caption_gap
        if cell_h < 100:
            # Defensive: if the title block left almost nothing, skip.
            c.showPage()
            pages_used += 1
            continue

        # Horizontally centre rows with fewer than `cols` cells so the
        # last (possibly short) row balances visually.
        row_w = n * cell_w + (n - 1) * GUTTER
        start_x = (PAGE_W - row_w) / 2

        for i, item in enumerate(slice_items):
            x = start_x + i * (cell_w + GUTTER)
            cy = y  # top of cell

            # Image tile
            c.setStrokeColor(HexColor("#E0E0E0"))
            c.setLineWidth(0.5)
            c.rect(x, cy - cell_h, cell_w, cell_h, fill=0, stroke=1)
            data = fetch_image(item.get("url") or "")
            if data:
                try:
                    img = ImageReader(io.BytesIO(data))
                    iw, ih = img.getSize()
                    scale = min(cell_w / iw, cell_h / ih)
                    dw, dh = iw * scale, ih * scale
                    c.drawImage(
                        img,
                        x + (cell_w - dw) / 2,
                        cy - cell_h + (cell_h - dh) / 2,
                        dw, dh, mask="auto",
                    )
                except Exception as e:
                    print(
                        f"  ! could not render marketing image {item.get('url')}: {e}",
                        file=sys.stderr,
                    )

            # Category pill, below image
            category = (item.get("category") or "other").upper()
            pill_text_w = stringWidth(category, HEADER_FONT, 7)
            pill_w = pill_text_w + 12
            pill_y = cy - cell_h - image_caption_gap - pill_h
            c.setFillColor(HexColor(primary_color))
            c.roundRect(x, pill_y, pill_w, pill_h, 4, fill=1, stroke=0)
            c.setFillColor(HexColor(contrasting_text(primary_color)))
            c.setFont(HEADER_FONT, 7)
            c.drawString(x + 6, pill_y + 4, category)

            # Description, below pill
            desc = item.get("description") or ""
            c.setFillColor(HexColor("#333333"))
            c.setFont(BODY_FONT, 9)
            wrapped = wrap_text(desc, BODY_FONT, 9, cell_w)[:desc_lines]
            for j, line in enumerate(wrapped):
                c.drawString(x, pill_y - 6 - (j + 1) * desc_line_h, line)

        c.showPage()
        pages_used += 1

    return page_num + pages_used


def favicon_page(c: canvas.Canvas, brand_name: str, brand: dict, page_num: int) -> None:
    favs = brand.get("favicons") or []
    draw_page_chrome(c, "Logos & Marks", page_num, brand_name)
    y = draw_section_title(c, "Favicon", "Favicons detected on the site.", PAGE_H - MARGIN - 30)
    if not favs:
        c.setFillColor(HexColor("#666666"))
        c.setFont(BODY_FONT, 11)
        c.drawString(MARGIN, y, "No favicons detected.")
        c.showPage()
        return

    from reportlab.pdfbase.pdfmetrics import stringWidth

    primary_color = (brand.get("primary_color") or "#111111")
    dark_hex = primary_color if primary_color.upper() != "#FFFFFF" else "#111111"

    box = 96
    x = MARGIN
    for url in favs[:4]:
        data = fetch_image(url)
        # Per-icon backdrop: if the favicon is light-on-transparent it would
        # vanish on white, so swap the tile to the brand colour. Otherwise
        # keep white with a faint border.
        bg_hex = _pick_contrasting_bg(data, dark_hex)
        on_white = bg_hex == "#FFFFFF"
        c.setFillColor(HexColor(bg_hex))
        c.rect(x, y - box, box, box, fill=1, stroke=0)
        if on_white:
            c.setStrokeColor(HexColor("#E0E0E0"))
            c.setLineWidth(0.5)
            c.rect(x, y - box, box, box, fill=0, stroke=1)
        if data:
            try:
                img = ImageReader(io.BytesIO(data))
                iw, ih = img.getSize()
                scale = min((box - 16) / iw, (box - 16) / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(img, x + (box - dw) / 2, y - box + (box - dh) / 2, dw, dh, mask="auto")
            except Exception as e:
                print(f"  ! could not render favicon {url}: {e}", file=sys.stderr)
        # Caption: filename only, truncated to fit the cell width so neighbouring
        # cells don't overlap. (URL strings were >300pt — cells are 96pt wide.)
        c.setFont(BODY_FONT, 7)
        c.setFillColor(HexColor("#666666"))
        basename = url.rsplit("/", 1)[-1] or url
        while basename and stringWidth(basename, BODY_FONT, 7) > box:
            basename = basename[:-1]
            if basename and stringWidth(basename + "…", BODY_FONT, 7) <= box:
                basename += "…"
                break
        c.drawString(x, y - box - 10, basename)
        x += box + GUTTER
    c.showPage()


def _hex_norm(c: str | None) -> str | None:
    if not c:
        return None
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return None
    return "#" + c.lower()


def _hex_distance(a: str, b: str) -> float:
    """Squared RGB distance between two hex colours. ~0 = identical,
    ~195000 = opposite corners of the colour cube."""
    try:
        ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
        return (ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2
    except Exception:
        return 1e9


def _css_colour_set(data: dict) -> set[str]:
    """Every distinct hex colour the CSS analyser counted across the
    actual chrome (after the Gutenberg-noise filter). Used to vet
    Bedrock's accent pick — if the vision model invented a colour
    that doesn't appear in the design system at all, it's almost
    certainly from a photograph."""
    style = data.get("style") or {}
    out: set[str] = set()
    # Brand-flagged colours from the analyser.
    brand_block = style.get("brand") or {}
    for k in ("primary_color", "secondary_color", "accent_color",
              "surface_color", "text_color"):
        v = _hex_norm(brand_block.get(k))
        if v:
            out.add(v)
    # All tonal-palette stops.
    palettes = (style.get("design_tokens") or {}).get("palettes") or {}
    for ramp in palettes.values():
        if isinstance(ramp, dict):
            for c in ramp.values():
                v = _hex_norm(c)
                if v:
                    out.add(v)
        elif isinstance(ramp, list):
            for c in ramp:
                v = _hex_norm(c)
                if v:
                    out.add(v)
    return out


def apply_bedrock_to_data(data: dict, b: dict) -> None:
    """Bedrock vision result is authoritative — overrides DOM-probe values.

    Exception: if Bedrock's accent_color is nowhere to be found in the
    CSS-extracted palette, it's almost certainly a colour sampled from
    a photograph (lawn grass on a university campus, a bright jumper in
    a lifestyle shot). Snap it back to primary in that case."""
    style = data.setdefault("style", {})
    brand = style.setdefault("brand", {})

    # Vet accent BEFORE applying. The CSS set was just rebuilt with the
    # noise filter, so anything we cross-reference here is from the
    # actual design system.
    bedrock_accent = _hex_norm(b.get("accent_color"))
    if bedrock_accent:
        css_set = _css_colour_set(data)
        if css_set:
            closest = min(
                (c for c in css_set), key=lambda c: _hex_distance(bedrock_accent, c)
            )
            # 1500 ≈ ~12 RGB units per channel — within "same shade" range.
            if _hex_distance(bedrock_accent, closest) > 1500:
                print(
                    f"  ! Bedrock accent {bedrock_accent} not present in CSS palette "
                    f"(closest {closest}); snapping to primary",
                    file=sys.stderr,
                )
                b = dict(b)
                b["accent_color"] = b.get("primary_color") or bedrock_accent
                # Drop the accent name too so we don't carry "Electric
                # Lime" forward for a brand that has no electric lime.
                if isinstance(b.get("color_names"), dict):
                    names = dict(b["color_names"])
                    names.pop("accent", None)
                    b["color_names"] = names

    for k_src, k_dst in [
        ("primary_color", "primary_color"),
        ("secondary_color", "secondary_color"),
        ("accent_color", "accent_color"),
        ("surface_color", "surface_color"),
        ("text_color", "text_color"),
    ]:
        v = b.get(k_src)
        if v:
            brand[k_dst] = v
    if b.get("color_names"):
        brand["color_names"] = b["color_names"]
    if b.get("tone_words"):
        brand["tone_words"] = b["tone_words"]
    if b.get("notes"):
        brand["notes"] = b["notes"]
    typography = style.setdefault("typography", {})
    if b.get("display_font_guess"):
        typography["primary_font"] = b["display_font_guess"]
    if b.get("body_font_guess"):
        typography["secondary_font"] = b["body_font_guess"]

    # Recompute the tonal palettes against the new brand colours so the gradients
    # we render later actually belong to the same colour family.
    tokens = style.setdefault("design_tokens", {})
    palettes = tokens.setdefault("palettes", {})
    for role in ("primary", "secondary", "accent"):
        color = brand.get(f"{role}_color")
        if color:
            try:
                palettes[role] = analyze_style.tint_shade_palette(color)
            except Exception:
                pass


def apply_probe_to_data(data: dict, probe: dict) -> None:
    """Override the YAML's frequency-derived brand bits with the probe's computed-style values."""
    style = data.setdefault("style", {})
    brand = style.setdefault("brand", {})
    if probe.get("primary_color"):
        brand["primary_color"] = probe["primary_color"]
    if probe.get("secondary_color"):
        brand["secondary_color"] = probe["secondary_color"]
    if probe.get("accent_color"):
        brand["accent_color"] = probe["accent_color"]
    typography = style.setdefault("typography", {})
    if probe.get("display_font"):
        typography["primary_font"] = probe["display_font"]
    if probe.get("body_font"):
        typography["secondary_font"] = probe["body_font"]
    if probe.get("primary_logo"):
        images = data.setdefault("images", {})
        imlist = images.setdefault("images", [])
        # remove any existing entry for this URL then re-insert at the top
        url = probe["primary_logo"]
        imlist = [im for im in imlist if im.get("url") != url]
        imlist.insert(0, {"url": url, "role": "logo", "source": "playwright_probe"})
        images["images"] = imlist


def apply_bedrock_assets_to_data(data: dict, classification: dict) -> None:
    """Rewrite image role tags using Bedrock's brand-asset triage.

    - brand_primary    → role: "brand_primary"  (the actual company logo)
    - brand_supporting → role: "brand_supporting" (trust marks / badges / "20 years experience")
    - customer_logo    → role: "customer_logo"   (excluded from the PDF)
    - irrelevant       → role left untouched

    Also stores a per-image `bedrock_description` so the PDF can label trust marks.
    """
    by_url = {item["url"]: item for item in classification.get("classifications", [])
              if item.get("url")}
    images = data.setdefault("images", {}).setdefault("images", [])
    for im in images:
        hit = by_url.get(im.get("url"))
        if not hit:
            continue
        category = hit.get("category")
        if category in {"brand_primary", "brand_supporting", "customer_logo"}:
            im["role"] = category
        if hit.get("description"):
            im["bedrock_description"] = hit["description"]
    if classification.get("notes"):
        data.setdefault("images", {})["bedrock_notes"] = classification["notes"]


def promote_favicons_to_supporting_marks(data: dict, classification: dict) -> None:
    """Favicons can be the brand mark itself OR a hijacked badge slot ('20 years
    experience'). When Bedrock tags a favicon URL as brand_supporting we move it
    into images.images so it shows on Trust Marks instead of the tiny Favicon page.
    Genuine favicons (anything tagged irrelevant or just a basic site icon) stay."""
    by_url = {item["url"]: item for item in classification.get("classifications", [])
              if item.get("url")}
    style = data.setdefault("style", {})
    brand = style.setdefault("brand", {})
    favs = list(brand.get("favicons") or [])
    images_block = data.setdefault("images", {})
    imlist = images_block.setdefault("images", [])
    existing_urls = {im.get("url") for im in imlist}

    surviving_favs: list[str] = []
    promoted = 0
    for url in favs:
        hit = by_url.get(url)
        if hit and hit.get("category") == "brand_supporting":
            if url not in existing_urls:
                imlist.append({
                    "url": url,
                    "role": "brand_supporting",
                    "source": "favicon_promoted",
                    "bedrock_description": hit.get("description", ""),
                })
                existing_urls.add(url)
                promoted += 1
            else:
                # Already in images.images — just make sure the role is right
                for im in imlist:
                    if im.get("url") == url:
                        im["role"] = "brand_supporting"
                        if hit.get("description"):
                            im["bedrock_description"] = hit["description"]
        else:
            surviving_favs.append(url)
    brand["favicons"] = surviving_favs
    if promoted:
        print(f"  Promoted {promoted} favicon(s) to brand_supporting (badges, not icons).",
              file=sys.stderr)


def apply_marketing_imagery_to_data(data: dict, marketing: dict) -> None:
    """Merge per-image marketing classifications into images.images[] and
    keep a top-level images.marketing_imagery list (suitable_for_ads-only,
    newest scoring first) so downstream tools don't need to refilter."""
    items = (marketing or {}).get("images") or []
    if not items:
        return

    by_url = {it.get("url"): it for it in items if it.get("url")}
    images_section = data.setdefault("images", {})
    imgs = images_section.setdefault("images", [])
    for im in imgs:
        m = by_url.get(im.get("url"))
        if not m:
            continue
        if m.get("category"):
            im["marketing_category"] = m["category"]
        if m.get("description"):
            im["marketing_description"] = m["description"]
        if m.get("subjects"):
            im["marketing_subjects"] = m["subjects"]
        if "suitable_for_ads" in m:
            im["suitable_for_ads"] = bool(m["suitable_for_ads"])

    # Top-level summary for the ads-worker.
    suitable = [
        {
            "url": m.get("url"),
            "category": m.get("category"),
            "description": m.get("description"),
            "subjects": m.get("subjects") or [],
        }
        for m in items
        if m.get("url") and m.get("suitable_for_ads")
    ]
    if suitable:
        images_section["marketing_imagery"] = suitable


def apply_bedrock_essence_to_data(data: dict, essence: dict) -> None:
    """Store the mission/services/strengths bundle under content.essence."""
    if not essence:
        return
    content = data.setdefault("content", {})
    keep = {}
    for k in ("mission_statement", "value_propositions", "core_services",
              "key_strengths", "tone_of_voice", "contact_details"):
        if essence.get(k):
            keep[k] = essence[k]
    if keep:
        content["essence"] = keep


def about_blurb_from_content(content: dict) -> str:
    paragraphs = content.get("paragraphs") or []
    candidates = []
    for p in paragraphs:
        text = (p.get("text") if isinstance(p, dict) else p) or ""
        text = text.strip()
        if 120 <= len(text) <= 360:
            candidates.append(text)
    return candidates[0] if candidates else (paragraphs[0]["text"] if paragraphs else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Website URL to crawl (e.g. https://example.com)")
    parser.add_argument("--from-yaml", help="Skip the crawl and use an existing brand YAML instead")
    parser.add_argument("-o", "--output", default="brand_guidelines.pdf", help="Output PDF path")
    parser.add_argument("--save-yaml", help="Also write the intermediate brand YAML to this path")
    parser.add_argument("--brand-name", help="Override brand name (default: derived from site)")
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    parser.add_argument("--include-plugin-css", action="store_true",
                        help="Include known-noise plugin stylesheets in style analysis.")
    parser.add_argument("--no-bedrock", action="store_true",
                        help="Skip the Bedrock vision call (default: on; needs AWS creds).")
    parser.add_argument("--no-probe", action="store_true",
                        help="Skip the Playwright DOM probe.")
    parser.add_argument("--screenshot-dir", default="brand_screenshots",
                        help="Folder for Playwright screenshots (default: brand_screenshots).")
    parser.add_argument("--extra-url", action="append", default=[],
                        help="Additional URL to screenshot (repeatable).")
    parser.add_argument("--bedrock-model", help="Override the Bedrock model ID.")
    parser.add_argument("--bedrock-region", help="Override the Bedrock region.")
    parser.add_argument("--consultancy-name", default=DEFAULT_CONSULTANCY_NAME,
                        help="Consultancy producing the guidelines (footer + credits page).")
    parser.add_argument("--consultancy-url", default=DEFAULT_CONSULTANCY_URL,
                        help="Consultancy website (credits page).")
    parser.add_argument("--consultancy-logo-url", default=DEFAULT_CONSULTANCY_LOGO_URL,
                        help="URL to the consultancy logo PNG (credits page).")
    parser.add_argument("--consultancy-tagline", default=DEFAULT_CONSULTANCY_TAGLINE,
                        help="Tagline shown on the credits page.")
    args = parser.parse_args()

    if not args.url and not args.from_yaml:
        parser.error("provide a URL, or --from-yaml PATH to reuse an existing brand YAML")
    if args.url and args.from_yaml:
        parser.error("provide either a URL or --from-yaml, not both")

    if args.from_yaml:
        data = yaml.safe_load(Path(args.from_yaml).read_text(encoding="utf-8"))
        probe = None
    else:
        data = build_brand.build_brand(
            args.url,
            max_pages=args.max_pages,
            timeout=args.timeout,
            user_agent=args.user_agent,
            include_plugin_css=args.include_plugin_css,
        )
        if args.save_yaml:
            Path(args.save_yaml).write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
                encoding="utf-8",
            )
            print(f"Saved brand YAML to {args.save_yaml}", file=sys.stderr)

        probe = None
        if not args.no_probe:
            print("Probing live site with Playwright (DOM hints + screenshots)...", file=sys.stderr)
            try:
                probe = probe_brand.probe_site(
                    args.url,
                    screenshot_dir=args.screenshot_dir,
                    extra_urls=args.extra_url,
                )
                ps = probe["summary"]
                print(f"  DOM probe: primary={ps['primary_color']} accent={ps['accent_color']} "
                      f"display={ps['display_font']} logo={ps['primary_logo']}", file=sys.stderr)
            except Exception as e:
                print(f"  ! probe failed ({e}); continuing without it.", file=sys.stderr)

        if probe and probe["summary"]:
            apply_probe_to_data(data, probe["summary"])

    # ---- Bedrock passes: gather screenshots from this run OR a previous one ----
    if not args.no_bedrock:
        if probe and probe.get("screenshots"):
            screenshots = list(probe["screenshots"])
        else:
            screenshots = sorted(str(p) for p in Path(args.screenshot_dir).glob("*.png")) \
                if Path(args.screenshot_dir).exists() else []
        # Bedrock caps images at 5MB; drop anything larger (typically the full-page shot).
        screenshots = [p for p in screenshots if Path(p).stat().st_size <= 5 * 1024 * 1024]

        if screenshots:
            # Pass 1: identity (colours, fonts, tone)
            try:
                dom_hints = (probe and probe.get("summary")) or {
                    "primary_color": (data.get("style") or {}).get("brand", {}).get("primary_color"),
                    "secondary_color": (data.get("style") or {}).get("brand", {}).get("secondary_color"),
                    "accent_color": (data.get("style") or {}).get("brand", {}).get("accent_color"),
                    "display_font": (data.get("style") or {}).get("typography", {}).get("primary_font"),
                    "body_font": (data.get("style") or {}).get("typography", {}).get("secondary_font"),
                }
                bedrock_summary = bedrock_brand.analyze_screenshots(
                    screenshots, dom_hints=dom_hints,
                    model_id=args.bedrock_model, region=args.bedrock_region,
                )
                print(f"  Bedrock identity: primary={bedrock_summary.get('primary_color')} "
                      f"secondary={bedrock_summary.get('secondary_color')} "
                      f"accent={bedrock_summary.get('accent_color')} "
                      f"display={bedrock_summary.get('display_font_guess')}", file=sys.stderr)
                apply_bedrock_to_data(data, bedrock_summary)
            except Exception as e:
                print(f"  ! Bedrock identity pass failed ({e}); keeping prior values.", file=sys.stderr)

            # Pass 1b: Design DNA — the visual contract every ad
            # should obey. Archetype + density + typography rules +
            # photography treatment + layout preference + reference
            # marks + voice-to-design rules + do-nots.
            try:
                style_so_far = data.get("style") or {}
                brand_so_far = style_so_far.get("brand") or {}
                typo_so_far = style_so_far.get("typography") or {}
                ctx_for_dna = {
                    "domain": data.get("domain"),
                    "brand_colors": {
                        "primary_color": brand_so_far.get("primary_color"),
                        "secondary_color": brand_so_far.get("secondary_color"),
                        "accent_color": brand_so_far.get("accent_color"),
                    },
                    "typography": {
                        "primary_font": typo_so_far.get("primary_font"),
                        "body_font": typo_so_far.get("secondary_font"),
                    },
                    "tone_words": brand_so_far.get("tone_words"),
                    "mission_statement": ((data.get("content") or {}).get("essence") or {}).get("mission_statement"),
                }
                design_dna = bedrock_brand.classify_design_dna(
                    screenshots, brand_context=ctx_for_dna,
                    model_id=args.bedrock_model, region=args.bedrock_region,
                )
                if isinstance(design_dna, dict) and design_dna.get("archetype"):
                    print(
                        f"  Bedrock design DNA: archetype={design_dna.get('archetype')} "
                        f"layout={design_dna.get('layout_preference')} "
                        f"density={design_dna.get('density')}",
                        file=sys.stderr,
                    )
                    style_so_far.setdefault("design_dna", design_dna)
                    data["style"] = style_so_far
            except Exception as e:
                print(f"  ! Bedrock design-DNA pass failed ({e}); skipping.", file=sys.stderr)

            # Pass 2: brand asset classification (logo vs partner-logo vs supporting marks)
            try:
                imgs = (data.get("images") or {}).get("images", [])
                image_candidates = [im["url"] for im in imgs
                                    if im.get("url") and (im.get("role") in {"logo", "header", "hero", "brand_primary", "brand_supporting"})]
                # Favicons too — WordPress sites often register supporting marks
                # (badges, accreditations) as the site icon, where they bypass
                # the regular image classification.
                favicon_candidates = list((data.get("style") or {}).get("brand", {}).get("favicons") or [])
                # Cap to avoid runaway token cost
                candidates = (image_candidates + favicon_candidates)[:50]
                if candidates:
                    domain = data.get("domain") or urlparse(data.get("start_url") or "").netloc
                    # Inline favicon bytes — their filenames are uninformative
                    # (e.g. "cropped-MicrosoftTeams-image-180x180.png") so the
                    # model needs to see the pixels to distinguish a real
                    # favicon from a hijacked "20 Years Experience" badge.
                    inline_urls = [u for u in favicon_candidates if u in candidates]
                    assets = bedrock_brand.classify_brand_assets(
                        screenshots, candidates, domain=domain,
                        inline_urls=inline_urls,
                        model_id=args.bedrock_model, region=args.bedrock_region,
                    )
                    cls = assets.get("classifications", [])
                    by_cat: dict[str, int] = {}
                    for item in cls:
                        by_cat[item.get("category", "?")] = by_cat.get(item.get("category", "?"), 0) + 1
                    print(f"  Bedrock assets: {by_cat}", file=sys.stderr)
                    apply_bedrock_assets_to_data(data, assets)
                    promote_favicons_to_supporting_marks(data, assets)
            except Exception as e:
                print(f"  ! Bedrock asset pass failed ({e}); keeping prior roles.", file=sys.stderr)

        # Pass 2b: marketing-imagery classification — runs OUTSIDE the
        # `if screenshots:` block because it only needs the candidate
        # image URLs (the model gets the pixel bytes per-image, not the
        # site-level screenshots). This pass still works even if
        # Playwright/Chromium failed earlier.
        try:
            imgs = (data.get("images") or {}).get("images", [])
            photo_roles = {"hero", "header", "content"}
            excluded_roles = {
                "brand_primary", "brand_supporting", "customer_logo",
                "logo", "nav", "footer", "icon", "social",
            }
            photo_candidates = [
                im["url"] for im in imgs
                if im.get("url")
                and im.get("role") in photo_roles
                and im.get("role") not in excluded_roles
            ][:30]
            if photo_candidates:
                domain = data.get("domain") or urlparse(data.get("start_url") or "").netloc
                marketing = bedrock_brand.classify_marketing_imagery(
                    photo_candidates, domain=domain,
                    model_id=args.bedrock_model, region=args.bedrock_region,
                )
                classified = marketing.get("images") or []
                suitable = sum(1 for it in classified if it.get("suitable_for_ads"))
                print(
                    f"  Bedrock marketing imagery: {len(classified)} classified, "
                    f"{suitable} suitable for ads (from {len(photo_candidates)} candidates)",
                    file=sys.stderr,
                )
                apply_marketing_imagery_to_data(data, marketing)
            else:
                print(
                    "  Bedrock marketing imagery: no candidate photos found",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"  ! Bedrock marketing-imagery pass failed ({e}); skipping.", file=sys.stderr)

        # Pass 3: brand essence (mission / services / strengths) — text-only, no screenshots needed
        try:
            content = data.get("content") or {}
            page_titles = list((content.get("page_titles") or {}).values())
            paragraphs_raw = content.get("paragraphs") or []
            paragraphs = [p.get("text") if isinstance(p, dict) else p for p in paragraphs_raw]
            paragraphs = [p for p in paragraphs if p]
            if page_titles or paragraphs:
                domain = data.get("domain") or urlparse(data.get("start_url") or "").netloc
                essence = bedrock_brand.extract_brand_essence(
                    domain=domain, page_titles=page_titles, paragraphs=paragraphs,
                    model_id=args.bedrock_model, region=args.bedrock_region,
                )
                services = essence.get("core_services") or []
                strengths = essence.get("key_strengths") or []
                print(f"  Bedrock essence: mission={'yes' if essence.get('mission_statement') else 'no'} "
                      f"services={len(services)} strengths={len(strengths)}", file=sys.stderr)
                apply_bedrock_essence_to_data(data, essence)
        except Exception as e:
            print(f"  ! Bedrock essence pass failed ({e}); no mission/services in PDF.", file=sys.stderr)

        # Pass 4: voice + messaging + personas + vocabulary. Reuses
        # the same page titles + paragraphs as the essence pass but
        # asks for a brand-strategist-level output: tone-of-voice
        # do/don't pairs, voice-spectrum sliders, messaging framework
        # (10/30/60/150-word pitches + tagline candidates), 2-4
        # personas, vocabulary preferred/avoid.
        try:
            content = data.get("content") or {}
            page_titles = list((content.get("page_titles") or {}).values())
            paragraphs_raw = content.get("paragraphs") or []
            paragraphs = [p.get("text") if isinstance(p, dict) else p for p in paragraphs_raw]
            paragraphs = [p for p in paragraphs if p]
            if page_titles or paragraphs:
                domain = data.get("domain") or urlparse(data.get("start_url") or "").netloc
                style_so_far = data.get("style") or {}
                brand_so_far = style_so_far.get("brand") or {}
                essence_so_far = (data.get("content") or {}).get("essence") or {}
                ctx_for_voice = {
                    "brand_name": essence_so_far.get("brand_name"),
                    "mission_statement": essence_so_far.get("mission_statement"),
                    "tone_words": brand_so_far.get("tone_words"),
                    "core_services": essence_so_far.get("core_services"),
                    "design_archetype": (style_so_far.get("design_dna") or {}).get("archetype"),
                }
                voice = bedrock_brand.extract_voice_and_messaging(
                    domain=domain, brand_context=ctx_for_voice,
                    page_titles=page_titles, paragraphs=paragraphs,
                    model_id=args.bedrock_model, region=args.bedrock_region,
                )
                personas = voice.get("personas") or []
                tone = voice.get("tone_of_voice") or {}
                print(
                    f"  Bedrock voice: personas={len(personas)} "
                    f"tone_examples={len(tone.get('examples') or [])} "
                    f"taglines={len((voice.get('messaging') or {}).get('tagline_candidates') or [])}",
                    file=sys.stderr,
                )
                content_block = data.setdefault("content", {})
                content_block["voice"] = voice
        except Exception as e:
            print(f"  ! Bedrock voice-messaging pass failed ({e}); skipping.", file=sys.stderr)

        # Persist enriched YAML if a save target was given
        if args.save_yaml:
            Path(args.save_yaml).write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
                encoding="utf-8",
            )
    style = data.get("style") or {}
    brand = style.get("brand") or {}
    typography = style.get("typography") or {}
    palettes = (style.get("design_tokens") or {}).get("palettes") or {}
    content = data.get("content") or {}
    images = data.get("images") or {}
    start_url = data.get("start_url") or ""

    brand_name = args.brand_name or brand_name_from(brand, start_url)
    blurb = about_blurb_from_content(content) or f"{brand_name} brand guidelines."

    c = canvas.Canvas(args.output, pagesize=landscape(A4))
    c.setTitle(f"{brand_name} Brand Guidelines")
    c.setAuthor(brand_name)

    palettes = (style.get("design_tokens") or {}).get("palettes") or palettes

    essence = content.get("essence") or {}
    # Find the brand_primary logo URL for the cover (falls back to legacy 'logo' role)
    cover_logo_url = None
    for im in images.get("images", []):
        if im.get("role") == "brand_primary":
            cover_logo_url = im.get("url")
            break
    if not cover_logo_url:
        for im in images.get("images", []):
            if im.get("role") == "logo":
                cover_logo_url = im.get("url")
                break

    # Cover screenshot — the homepage above-the-fold capture from the
    # Playwright probe. Falls through quietly if Playwright failed.
    cover_screenshot = None
    home_fold = Path(args.screenshot_dir) / "01_home_fold.png"
    if home_fold.exists():
        cover_screenshot = str(home_fold)

    cover_page(c, brand_name, args.year, brand_color=brand.get("primary_color"),
               logo_url=cover_logo_url, screenshot_path=cover_screenshot,
               consultancy_name=args.consultancy_name,
               consultancy_logo_url=args.consultancy_logo_url)
    about_page(c, brand_name, blurb, page_num=2)
    next_page = 3
    # Contact lives right after About — business info grouped at the front of
    # the book, not buried before the credits page.
    next_page = contact_page(c, brand_name, essence, brand, page_num=next_page)
    next_page = mission_page(c, brand_name, essence, brand, page_num=next_page)
    next_page = core_services_page(c, brand_name, essence, brand, page_num=next_page)
    next_page = strengths_page(c, brand_name, essence, brand, page_num=next_page)
    palette_page(c, brand_name, brand, palettes, page_num=next_page); next_page += 1
    gradients_page(c, brand_name, brand, palettes, page_num=next_page); next_page += 1
    next_page = supporting_pages(c, brand_name, palettes, brand, start_page=next_page)
    next_page = design_dna_page(
        c, brand_name, style.get("design_dna") or {}, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    # Voice + messaging + personas + vocabulary — Tier 1 brand-book
    # additions. Each renderer falls through silently if its source
    # data is missing.
    voice_section = (content.get("voice") or {})
    next_page = voice_page(
        c, brand_name, voice_section, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    next_page = voice_spectrum_page(
        c, brand_name, voice_section, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    next_page = messaging_page(
        c, brand_name, voice_section, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    next_page = personas_page(
        c, brand_name, voice_section, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    next_page = vocabulary_page(
        c, brand_name, voice_section, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    next_page = ui_components_page(
        c, brand_name, brand, typography, page_num=next_page,
    )
    typography_page(c, brand_name, typography, page_num=next_page); next_page += 1
    next_page = logos_pages(c, brand_name, images, start_url, start_page=next_page,
                             primary_color=brand.get("primary_color") or "#111111")
    next_page = supporting_marks_page(c, brand_name, images, page_num=next_page)
    next_page = photography_page(
        c, brand_name, images, page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    next_page = photography_dos_donts_page(
        c, brand_name, images, style.get("design_dna") or {},
        page_num=next_page,
        primary_color=brand.get("primary_color") or "#111111",
    )
    favicon_page(c, brand_name, brand, page_num=next_page); next_page += 1
    consultancy_credits_page(
        c, brand_name,
        consultancy_name=args.consultancy_name,
        consultancy_url=args.consultancy_url,
        consultancy_logo_url=args.consultancy_logo_url,
        consultancy_tagline=args.consultancy_tagline,
        page_num=next_page,
    )

    c.save()
    print(f"Wrote {args.output} ({brand_name}).", file=sys.stderr)


if __name__ == "__main__":
    main()
