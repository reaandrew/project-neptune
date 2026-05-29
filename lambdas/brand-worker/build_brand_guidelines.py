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
    consultancy_name: str = DEFAULT_CONSULTANCY_NAME,
    consultancy_logo_url: str | None = DEFAULT_CONSULTANCY_LOGO_URL,
) -> None:
    bg = brand_color or "#000000"
    c.setFillColor(HexColor(bg))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    text_color = contrasting_text(bg)
    c.setFillColor(HexColor(text_color))

    # Render the brand logo top-left if available. Many web logos are
    # transparent PNGs intended to sit on a coloured background, so this
    # usually composes fine on the brand-coloured cover.
    if logo_url:
        data = fetch_image(logo_url)
        if data:
            try:
                img = ImageReader(io.BytesIO(data))
                iw, ih = img.getSize()
                max_w = 320
                max_h = 140
                scale = min(max_w / iw, max_h / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(
                    img, MARGIN, PAGE_H - MARGIN - dh,
                    dw, dh, mask="auto",
                )
            except Exception as e:
                print(f"  ! could not render cover logo {logo_url}: {e}", file=sys.stderr)

    c.setFont(HEADER_FONT, 64)
    c.drawString(MARGIN, PAGE_H / 2 - 30, brand_name)
    c.setFont(BODY_FONT, 22)
    c.drawString(MARGIN, PAGE_H / 2 - 66, "Brand Guidelines")
    c.setFont(BODY_FONT, 14)
    c.drawString(MARGIN, MARGIN, str(year))
    # Consultancy logo bottom-right (slightly larger than internal-page footer)
    draw_consultancy_footer_logo(
        c, consultancy_logo_url, consultancy_name,
        target_h=26, on_dark=(contrasting_text(bg) == "#FFFFFF"),
    )
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
    primary_h = min(300, y - MARGIN - 90)
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

    # Smaller companion tile underneath.
    companion_h = 90
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
    """Render a 'Photography' page: the brand's marketing imagery
    organised by Bedrock-assigned category, each cell captioned with the
    category + a short description.

    Returns the next page number. If no marketing imagery was
    classified, returns page_num unchanged (page is skipped)."""
    marketing = (images or {}).get("marketing_imagery") or []
    if not marketing:
        return page_num

    from reportlab.pdfbase.pdfmetrics import stringWidth

    # Sort: lifestyle/product/context first (the categories most useful
    # for ad references), then team/testimonial/other.
    category_order = {
        "lifestyle": 0, "product": 1, "context": 2,
        "team": 3, "testimonial": 4, "decorative": 5, "other": 6,
    }
    items = sorted(
        marketing,
        key=lambda it: category_order.get(it.get("category") or "other", 9),
    )[:6]

    draw_page_chrome(c, "Photography", page_num, brand_name)
    y = draw_section_title(
        c,
        "Brand Photography",
        "Real photography pulled from the site, categorised so designers and "
        "the ad generator can pick the right shot for each campaign.",
        PAGE_H - MARGIN - 30,
    )

    cols = 3
    cell_w = (PAGE_W - 2 * MARGIN - GUTTER * (cols - 1)) / cols

    # Vertical budget on landscape A4: PAGE_H (~595) minus top margin,
    # title block (~80), and a footer reservation of ~60 leaves about
    # 400pt for two rows of cells. Each row = image + pill + 2 lines of
    # description + spacing.
    pill_h = 14
    desc_lines = 2
    desc_line_h = 11
    caption_block = 8 + pill_h + 4 + desc_lines * desc_line_h  # gap + pill + gap + lines
    inter_row_gap = 12
    cell_h = 140
    row_pitch = cell_h + caption_block + inter_row_gap

    # Reserve room above the footer (the page chrome footer sits ~30pt
    # above the page bottom). Refuse to render anything that would fall
    # into the footer band.
    bottom_safe = MARGIN + 40

    for i, item in enumerate(items):
        row, col = divmod(i, cols)
        x = MARGIN + col * (cell_w + GUTTER)
        cy = y - row * row_pitch

        # Skip this cell entirely if it would intersect the footer.
        if cy - cell_h - caption_block < bottom_safe:
            continue

        # Image tile (with faint border)
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
                print(f"  ! could not render marketing image {item.get('url')}: {e}", file=sys.stderr)

        # Category pill — sits just below the image tile.
        category = (item.get("category") or "other").upper()
        pill_text_w = stringWidth(category, HEADER_FONT, 7)
        pill_w = pill_text_w + 12
        pill_y = cy - cell_h - 8 - pill_h  # 8pt gap from image bottom
        c.setFillColor(HexColor(primary_color))
        c.roundRect(x, pill_y, pill_w, pill_h, 4, fill=1, stroke=0)
        c.setFillColor(HexColor(contrasting_text(primary_color)))
        c.setFont(HEADER_FONT, 7)
        c.drawString(x + 6, pill_y + 4, category)

        # Description — capped at 2 lines so the cell stays in budget.
        desc = item.get("description") or ""
        c.setFillColor(HexColor("#333333"))
        c.setFont(BODY_FONT, 9)
        wrapped = wrap_text(desc, BODY_FONT, 9, cell_w)[:desc_lines]
        for j, line in enumerate(wrapped):
            c.drawString(x, pill_y - 4 - (j + 1) * desc_line_h, line)

    c.showPage()
    return page_num + 1


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


def apply_bedrock_to_data(data: dict, b: dict) -> None:
    """Bedrock vision result is authoritative — overrides DOM-probe values."""
    style = data.setdefault("style", {})
    brand = style.setdefault("brand", {})
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

    cover_page(c, brand_name, args.year, brand_color=brand.get("primary_color"),
               logo_url=cover_logo_url, consultancy_name=args.consultancy_name,
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
    typography_page(c, brand_name, typography, page_num=next_page); next_page += 1
    next_page = logos_pages(c, brand_name, images, start_url, start_page=next_page,
                             primary_color=brand.get("primary_color") or "#111111")
    next_page = supporting_marks_page(c, brand_name, images, page_num=next_page)
    next_page = photography_page(
        c, brand_name, images, page_num=next_page,
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
