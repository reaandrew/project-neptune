#!/usr/bin/env python3
"""Analyse a site's HTML/CSS artifacts and emit design-guideline YAML.

Captures: brand colors (with usage context), typography (families/sizes/weights),
border-radius vocabulary, favicon, theme-color, Google Fonts, and source stylesheets.
"""

import argparse
import colorsys
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import unquote, urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

from crawler import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, iter_pages

# ---------- color parsing ----------

NAMED_COLORS = {
    "aliceblue": "#f0f8ff", "antiquewhite": "#faebd7", "aqua": "#00ffff",
    "aquamarine": "#7fffd4", "azure": "#f0ffff", "beige": "#f5f5dc",
    "bisque": "#ffe4c4", "black": "#000000", "blanchedalmond": "#ffebcd",
    "blue": "#0000ff", "blueviolet": "#8a2be2", "brown": "#a52a2a",
    "burlywood": "#deb887", "cadetblue": "#5f9ea0", "chartreuse": "#7fff00",
    "chocolate": "#d2691e", "coral": "#ff7f50", "cornflowerblue": "#6495ed",
    "cornsilk": "#fff8dc", "crimson": "#dc143c", "cyan": "#00ffff",
    "darkblue": "#00008b", "darkcyan": "#008b8b", "darkgoldenrod": "#b8860b",
    "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9", "darkgreen": "#006400",
    "darkkhaki": "#bdb76b", "darkmagenta": "#8b008b", "darkolivegreen": "#556b2f",
    "darkorange": "#ff8c00", "darkorchid": "#9932cc", "darkred": "#8b0000",
    "darksalmon": "#e9967a", "darkseagreen": "#8fbc8f", "darkslateblue": "#483d8b",
    "darkslategray": "#2f4f4f", "darkturquoise": "#00ced1", "darkviolet": "#9400d3",
    "deeppink": "#ff1493", "deepskyblue": "#00bfff", "dimgray": "#696969",
    "dodgerblue": "#1e90ff", "firebrick": "#b22222", "floralwhite": "#fffaf0",
    "forestgreen": "#228b22", "fuchsia": "#ff00ff", "gainsboro": "#dcdcdc",
    "ghostwhite": "#f8f8ff", "gold": "#ffd700", "goldenrod": "#daa520",
    "gray": "#808080", "grey": "#808080", "green": "#008000",
    "greenyellow": "#adff2f", "honeydew": "#f0fff0", "hotpink": "#ff69b4",
    "indianred": "#cd5c5c", "indigo": "#4b0082", "ivory": "#fffff0",
    "khaki": "#f0e68c", "lavender": "#e6e6fa", "lawngreen": "#7cfc00",
    "lemonchiffon": "#fffacd", "lightblue": "#add8e6", "lightcoral": "#f08080",
    "lightcyan": "#e0ffff", "lightgoldenrodyellow": "#fafad2", "lightgray": "#d3d3d3",
    "lightgrey": "#d3d3d3", "lightgreen": "#90ee90", "lightpink": "#ffb6c1",
    "lightsalmon": "#ffa07a", "lightseagreen": "#20b2aa", "lightskyblue": "#87cefa",
    "lightsteelblue": "#b0c4de", "lightyellow": "#ffffe0", "lime": "#00ff00",
    "limegreen": "#32cd32", "linen": "#faf0e6", "magenta": "#ff00ff",
    "maroon": "#800000", "mediumaquamarine": "#66cdaa", "mediumblue": "#0000cd",
    "mediumorchid": "#ba55d3", "mediumpurple": "#9370db", "mediumseagreen": "#3cb371",
    "mediumslateblue": "#7b68ee", "mediumspringgreen": "#00fa9a", "mediumturquoise": "#48d1cc",
    "mediumvioletred": "#c71585", "midnightblue": "#191970", "mintcream": "#f5fffa",
    "navajowhite": "#ffdead", "navy": "#000080", "oldlace": "#fdf5e6",
    "olive": "#808000", "olivedrab": "#6b8e23", "orange": "#ffa500",
    "orangered": "#ff4500", "orchid": "#da70d6", "palegoldenrod": "#eee8aa",
    "palegreen": "#98fb98", "paleturquoise": "#afeeee", "palevioletred": "#db7093",
    "papayawhip": "#ffefd5", "peachpuff": "#ffdab9", "peru": "#cd853f",
    "pink": "#ffc0cb", "plum": "#dda0dd", "powderblue": "#b0e0e6",
    "purple": "#800080", "rebeccapurple": "#663399", "red": "#ff0000",
    "rosybrown": "#bc8f8f", "royalblue": "#4169e1", "saddlebrown": "#8b4513",
    "salmon": "#fa8072", "sandybrown": "#f4a460", "seagreen": "#2e8b57",
    "seashell": "#fff5ee", "sienna": "#a0522d", "silver": "#c0c0c0",
    "skyblue": "#87ceeb", "slateblue": "#6a5acd", "slategray": "#708090",
    "snow": "#fffafa", "springgreen": "#00ff7f", "steelblue": "#4682b4",
    "tan": "#d2b48c", "teal": "#008080", "thistle": "#d8bfd8",
    "tomato": "#ff6347", "turquoise": "#40e0d0", "violet": "#ee82ee",
    "wheat": "#f5deb3", "white": "#ffffff", "whitesmoke": "#f5f5f5",
    "yellow": "#ffff00", "yellowgreen": "#9acd32",
}

HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
RGB_RE = re.compile(r"rgba?\(([^)]+)\)", re.IGNORECASE)
HSL_RE = re.compile(r"hsla?\(([^)]+)\)", re.IGNORECASE)
# Use non-hyphen, non-word boundaries so we don't match `cyan` inside
# `.has-light-green-cyan-color` or `var(--cyan-bluish-gray)`.
NAMED_RE = re.compile(
    r"(?<![\w-])(" + "|".join(NAMED_COLORS) + r")(?![\w-])",
    re.IGNORECASE,
)


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    h = hex_str.lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    elif len(h) == 4:
        h = "".join(c * 2 for c in h[:3])
    elif len(h) == 8:
        h = h[:6]
    elif len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def normalize_hex(hex_str: str) -> str | None:
    rgb = _hex_to_rgb(hex_str)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}" if rgb else None


def _parse_rgb(args_str: str) -> str | None:
    cleaned = args_str.replace("/", ",")
    parts = [p.strip() for p in re.split(r"[\s,]+", cleaned) if p.strip()]
    if len(parts) < 3:
        return None
    try:
        rgb = []
        for p in parts[:3]:
            if p.endswith("%"):
                rgb.append(round(float(p.rstrip("%")) * 2.55))
            else:
                rgb.append(int(float(p)))
        r, g, b = (max(0, min(255, v)) for v in rgb)
        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return None


def _parse_hsl(args_str: str) -> str | None:
    cleaned = args_str.replace("/", ",")
    parts = [p.strip() for p in re.split(r"[\s,]+", cleaned) if p.strip()]
    if len(parts) < 3:
        return None
    try:
        h = float(re.sub(r"deg|turn|rad", "", parts[0])) / 360.0
        s = float(parts[1].rstrip("%")) / 100.0
        l = float(parts[2].rstrip("%")) / 100.0
        r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
    except ValueError:
        return None


def find_colors(value: str) -> list[str]:
    """Return normalized #rrggbb colors found in a CSS value (in order)."""
    out: list[str] = []
    for m in HEX_RE.finditer(value):
        nh = normalize_hex(m.group(1))
        if nh:
            out.append(nh)
    for m in RGB_RE.finditer(value):
        c = _parse_rgb(m.group(1))
        if c:
            out.append(c)
    for m in HSL_RE.finditer(value):
        c = _parse_hsl(m.group(1))
        if c:
            out.append(c)
    for m in NAMED_RE.finditer(value):
        out.append(NAMED_COLORS[m.group(1).lower()])
    return out


def is_grayscale(hex_color: str, tolerance: int = 8) -> bool:
    rgb = _hex_to_rgb(hex_color.lstrip("#"))
    if not rgb:
        return True
    r, g, b = rgb
    return max(r, g, b) - min(r, g, b) <= tolerance


def luminance(hex_color: str) -> float:
    rgb = _hex_to_rgb(hex_color.lstrip("#"))
    if not rgb:
        return 0.0
    r, g, b = (c / 255.0 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------- design tokens derived from brand colors ----------

def hex_to_hsl(hex_color: str) -> tuple[float, float, float]:
    rgb = _hex_to_rgb(hex_color.lstrip("#"))
    if not rgb:
        return 0.0, 0.0, 0.0
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def hsl_to_hex(h: float, s: float, l: float) -> str:
    h = h % 1.0
    s = max(0.0, min(1.0, s))
    l = max(0.0, min(1.0, l))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def tint_shade_palette(hex_color: str) -> dict:
    """Tailwind-style 50–900 scale derived from a single hex color."""
    h, s, l = hex_to_hsl(hex_color)
    # Target lightness per step. 500 = the brand color itself.
    targets = {
        "50":  0.97, "100": 0.93, "200": 0.86, "300": 0.76, "400": 0.66,
        "500": l,
        "600": max(0.0, l * 0.85),
        "700": max(0.0, l * 0.70),
        "800": max(0.0, l * 0.55),
        "900": max(0.0, l * 0.40),
    }
    # Slightly desaturate the lightest tints so they read as off-whites, not washed-out brand.
    sat_for = {"50": s * 0.45, "100": s * 0.6, "200": s * 0.8}
    return {step: hsl_to_hex(h, sat_for.get(step, s), tl) for step, tl in targets.items()}


def color_harmonies(hex_color: str) -> dict:
    h, s, l = hex_to_hsl(hex_color)
    return {
        "complement": hsl_to_hex(h + 0.5, s, l),
        "analogous": [hsl_to_hex(h + 1 / 12, s, l), hsl_to_hex(h - 1 / 12, s, l)],
        "triadic": [hsl_to_hex(h + 1 / 3, s, l), hsl_to_hex(h + 2 / 3, s, l)],
        "split_complement": [hsl_to_hex(h + 5 / 12, s, l), hsl_to_hex(h + 7 / 12, s, l)],
        "tetradic": [hsl_to_hex(h + 0.25, s, l), hsl_to_hex(h + 0.5, s, l), hsl_to_hex(h + 0.75, s, l)],
        "monochrome_darker": hsl_to_hex(h, s, max(0.0, l - 0.20)),
        "monochrome_lighter": hsl_to_hex(h, s, min(1.0, l + 0.20)),
    }


def gradient_suite(primary: str, secondary: str | None) -> dict:
    primary_palette = tint_shade_palette(primary)
    complement = color_harmonies(primary)["complement"]
    out = {
        "primary_subtle": f"linear-gradient(180deg, {primary_palette['100']} 0%, {primary} 100%)",
        "primary_deep": f"linear-gradient(180deg, {primary} 0%, {primary_palette['800']} 100%)",
        "primary_diagonal": f"linear-gradient(135deg, {primary_palette['300']} 0%, {primary_palette['700']} 100%)",
        "primary_to_complement": f"linear-gradient(90deg, {primary} 0%, {complement} 100%)",
        "primary_radial": f"radial-gradient(circle at 30% 30%, {primary_palette['400']} 0%, {primary_palette['800']} 100%)",
        "primary_glass": f"linear-gradient(135deg, {primary}cc 0%, {primary_palette['700']}99 100%)",
    }
    if secondary:
        sec_palette = tint_shade_palette(secondary)
        out.update({
            "primary_to_secondary": f"linear-gradient(135deg, {primary} 0%, {secondary} 100%)",
            "secondary_subtle": f"linear-gradient(180deg, {sec_palette['100']} 0%, {secondary} 100%)",
            "tri_stop": f"linear-gradient(90deg, {primary} 0%, {secondary} 50%, {primary_palette['800']} 100%)",
        })
    return out


def _rel_lum(hex_color: str) -> float:
    rgb = _hex_to_rgb(hex_color.lstrip("#"))
    if not rgb:
        return 0.0
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1: str, c2: str) -> float:
    l1, l2 = _rel_lum(c1), _rel_lum(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def contrast_report(bg: str) -> dict:
    vs_white = contrast_ratio("#ffffff", bg)
    vs_black = contrast_ratio("#000000", bg)
    best = "#ffffff" if vs_white >= vs_black else "#000000"
    best_ratio = max(vs_white, vs_black)
    return {
        "vs_white": vs_white,
        "vs_black": vs_black,
        "recommended_text": best,
        "wcag_aa_large": best_ratio >= 3.0,
        "wcag_aa_normal": best_ratio >= 4.5,
        "wcag_aaa_normal": best_ratio >= 7.0,
    }


def _spec(w: int, h: int, ratio: str, notes: str) -> dict:
    return {"width": w, "height": h, "aspect_ratio": ratio, "notes": notes}


SOCIAL_MEDIA_AD_SPECS = {
    "facebook": {
        "feed_square":     _spec(1080, 1080, "1:1",   "Standard feed image ad"),
        "feed_portrait":   _spec(1080, 1350, "4:5",   "Max screen area on mobile feed (Meta's recommended ratio)"),
        "feed_landscape":  _spec(1200,  628, "1.91:1", "Link/share preview image"),
        "stories":         _spec(1080, 1920, "9:16",  "Full-screen vertical; keep CTA in top 80%"),
        "reels":           _spec(1080, 1920, "9:16",  "Vertical short-form"),
        "carousel":        _spec(1080, 1080, "1:1",   "Each carousel card; same size for all cards"),
        "marketplace":     _spec(1200,  628, "1.91:1", "Marketplace placement"),
        "cover_photo":     _spec(1640,  859, "1.91:1", "Page cover (desktop 820×312, mobile 640×360 visible area)"),
    },
    "instagram": {
        "feed_square":     _spec(1080, 1080, "1:1",   "Classic Instagram feed"),
        "feed_portrait":   _spec(1080, 1350, "4:5",   "Tallest allowed in feed — most pixels on mobile"),
        "feed_landscape":  _spec(1080,  566, "1.91:1", "Landscape feed post"),
        "stories":         _spec(1080, 1920, "9:16",  "Avoid top/bottom 250px (profile + CTA overlay)"),
        "reels":           _spec(1080, 1920, "9:16",  "Vertical short-form video/image"),
        "explore":         _spec(1080, 1080, "1:1",   "Explore tab ad"),
        "shopping_tag":    _spec(1080, 1080, "1:1",   "Shoppable feed post"),
    },
    "linkedin": {
        "single_image_horizontal": _spec(1200,  627, "1.91:1", "Sponsored content (most common)"),
        "single_image_square":     _spec(1200, 1200, "1:1",   "Square feed ad"),
        "single_image_vertical":   _spec(  628, 1200, "1:1.91", "Vertical placement (mobile-first)"),
        "carousel_card":           _spec(1080, 1080, "1:1",   "Carousel ad — each card"),
        "message_ad":              _spec(  300,  250, "6:5",  "Banner inside InMail message"),
        "company_cover":           _spec(1128,  191, "5.9:1", "Page cover image"),
    },
    "twitter_x": {
        "single_image":            _spec(1200,  675, "16:9", "Standard image tweet"),
        "single_image_square":     _spec(1200, 1200, "1:1",  "Square image tweet"),
        "website_card":            _spec(1200,  628, "1.91:1", "Image with link card"),
        "multi_image_2up":         _spec(1200,  600, "2:1",  "Two-image tweet (per image area)"),
        "header":                  _spec(1500,  500, "3:1",  "Profile header banner"),
    },
    "pinterest": {
        "standard_pin":            _spec(1000, 1500, "2:3",  "Recommended ratio for Pin discovery"),
        "square_pin":              _spec(1000, 1000, "1:1",  "Square pin"),
        "long_pin":                _spec(1000, 2100, "1:2.1", "Maximum length before truncation"),
        "idea_pin":                _spec(1080, 1920, "9:16", "Idea/Story Pin"),
        "video_pin":               _spec(1080, 1920, "9:16", "Vertical video pin"),
    },
    "tiktok": {
        "in_feed":                 _spec(1080, 1920, "9:16", "Vertical video/image in feed"),
        "topview":                 _spec(1080, 1920, "9:16", "First impression takeover"),
        "spark_ad":                _spec(1080, 1920, "9:16", "Boost organic post"),
    },
    "snapchat": {
        "single_image":            _spec(1080, 1920, "9:16", "Full-screen vertical"),
        "story_ad":                _spec(1080, 1920, "9:16", "Between stories"),
    },
    "youtube": {
        "in_stream_skippable":     _spec(1920, 1080, "16:9", "Pre/mid/post-roll video"),
        "thumbnail":               _spec(1280,  720, "16:9", "Custom video thumbnail"),
        "channel_banner":          _spec(2560, 1440, "16:9", "Safe area for all devices: 1546×423 center"),
        "display_companion":       _spec(300,   250, "6:5",  "Companion banner alongside in-stream"),
    },
    "google_display_network": {
        "medium_rectangle":        _spec(300,   250, "6:5",  "MPU — most universally accepted size"),
        "large_rectangle":         _spec(336,   280, "6:5",  "Larger MPU"),
        "leaderboard":             _spec(728,    90, "8.1:1", "Top-of-page banner"),
        "large_leaderboard":       _spec(970,    90, "10.8:1", "Wider top-of-page banner"),
        "wide_skyscraper":         _spec(160,   600, "4:15", "Side rail vertical"),
        "half_page":               _spec(300,   600, "1:2",  "Tall side rail (high engagement)"),
        "mobile_banner":           _spec(320,    50, "6.4:1", "Mobile top/bottom strip"),
        "large_mobile_banner":     _spec(320,   100, "16:5", "Taller mobile banner"),
        "billboard":               _spec(970,   250, "3.88:1", "Premium top-of-page"),
    },
}


def semantic_suggestions(primary: str) -> dict:
    """Conventional semantic colors. Info derives from the brand hue when sensible."""
    h, s, l = hex_to_hsl(primary)
    info = primary if 0.55 <= h <= 0.7 else hsl_to_hex(0.6, max(0.6, s), 0.5)
    return {
        "success": "#22c55e",
        "warning": "#f59e0b",
        "danger":  "#ef4444",
        "info":    info,
        "muted":   "#6b7280",
    }


# ---------- CSS scanning ----------

DECL_RE = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;}{]+)")
FONTFACE_RE = re.compile(r"@font-face\s*\{([^}]+)\}", re.IGNORECASE | re.DOTALL)
KEYFRAMES_RE = re.compile(r"@(?:-webkit-|-moz-|-o-)?keyframes\s+[^{]+\{(?:[^{}]|\{[^{}]*\})*\}", re.IGNORECASE)
URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", re.IGNORECASE)


def clean_value(value: str) -> str:
    """Strip !important, trailing junk, and outer whitespace."""
    return re.sub(r"!\s*important\b", "", value, flags=re.IGNORECASE).strip()


def value_has_garbage(value: str) -> bool:
    """True if the value contains var()/calc()/parens we can't reliably parse."""
    return "var(" in value or "calc(" in value or "(" in value

COLOR_PROPS = {
    "color", "background", "background-color", "border", "border-color",
    "border-top", "border-right", "border-bottom", "border-left",
    "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
    "outline", "outline-color", "fill", "stroke", "box-shadow", "text-shadow",
    "caret-color", "column-rule-color", "text-decoration-color",
}

SPACING_PROPS = {
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "gap", "grid-gap", "column-gap", "row-gap",
}

LENGTH_RE = re.compile(r"-?\d+(?:\.\d+)?(?:px|rem|em|%)?", re.IGNORECASE)

CONTEXT_OF = {
    "color": "text",
    "fill": "text",
    "background": "background",
    "background-color": "background",
}
for prop in COLOR_PROPS:
    CONTEXT_OF.setdefault(prop, "border" if "border" in prop else "other")


def clean_font_family(value: str) -> list[str]:
    """'Roboto', \"Open Sans\", sans-serif → ['Roboto', 'Open Sans', 'sans-serif']."""
    out = []
    for part in value.split(","):
        name = part.strip().strip("'\"").strip()
        # Drop tokens with parens (var/calc residue), CSS keywords, or empty.
        if not name or any(c in name for c in "()"):
            continue
        if name.startswith("--") or name.lower() in {"inherit", "initial", "unset", "revert"}:
            continue
        if not re.match(r"^[A-Za-z][A-Za-z0-9 _\-]*$", name):
            continue
        out.append(name)
    return out


def parse_css(css_text: str, accum: dict):
    """Mutates accum dict with counters/lists for various style facts."""
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)

    for m in FONTFACE_RE.finditer(css_text):
        block = m.group(1)
        family = None
        src = None
        for dm in DECL_RE.finditer(block):
            prop = dm.group(1).lower().strip()
            val = clean_value(dm.group(2))
            if prop == "font-family":
                fams = clean_font_family(val)
                if fams:
                    family = fams[0]
            elif prop == "src":
                url_match = URL_RE.search(val)
                if url_match:
                    src = url_match.group(1)
        if family:
            accum["font_face"][family].add(src or "")

    # Drop @font-face and @keyframes — keyframes pollute the color palette badly
    # (animation libraries cycle through every color of the rainbow).
    css_clean = FONTFACE_RE.sub("", css_text)
    css_clean = KEYFRAMES_RE.sub("", css_clean)

    # Drop Gutenberg / WordPress preset utility-class rules — these
    # ship in every WP site and pollute the palette with stock colours
    # the brand never wears (e.g. .has-vivid-green-cyan-color {color:
    # #00d084} on edgehill.ac.uk).
    css_clean = strip_noise_rules(css_clean)

    generic_fonts = {
        "serif", "sans-serif", "monospace", "cursive", "fantasy",
        "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded",
        "emoji", "math", "fangsong",
    }
    icon_fonts = {
        "fontawesome", "font awesome", "font awesome 5 brands", "font awesome 5 free",
        "font awesome 5 solid", "font awesome 6 brands", "font awesome 6 free",
        "glyphicons halflings", "material icons", "material symbols outlined",
        "dashicons", "genericons", "icomoon", "ionicons", "themify",
        "eleganticons", "simple-line-icons", "feather",
    }

    for m in DECL_RE.finditer(css_clean):
        prop = m.group(1).lower().strip()
        val = clean_value(m.group(2))
        if not val:
            continue

        if prop in COLOR_PROPS:
            for c in find_colors(val):
                accum["colors"][c] += 1
                accum["colors_by_context"][CONTEXT_OF.get(prop, "other")][c] += 1
        elif prop == "font-family":
            for fam in clean_font_family(val):
                low = fam.lower()
                if low in generic_fonts:
                    accum["font_generic"][low] += 1
                elif low in icon_fonts or "icon" in low or "awesome" in low:
                    accum["icon_fonts"][fam] += 1
                else:
                    accum["fonts"][fam] += 1
        elif prop in ("font-size", "font-weight", "line-height", "letter-spacing"):
            if value_has_garbage(val):
                continue
            token = val.split()[0]
            bucket = {"font-size": "font_sizes", "font-weight": "font_weights",
                      "line-height": "line_heights", "letter-spacing": "letter_spacings"}[prop]
            accum[bucket][token] += 1
        elif prop in ("border-radius", "border-top-left-radius", "border-top-right-radius",
                      "border-bottom-left-radius", "border-bottom-right-radius"):
            if value_has_garbage(val):
                continue
            accum["border_radii"][val.split()[0]] += 1
        elif prop in SPACING_PROPS:
            if value_has_garbage(val):
                continue
            for token in LENGTH_RE.findall(val):
                if token in ("0", "-0"):
                    accum["spacing"]["0"] += 1
                else:
                    accum["spacing"][token] += 1
        elif prop == "box-shadow":
            if value_has_garbage(val) or val.lower() in ("none", "inherit"):
                continue
            normalized = re.sub(r"\s+", " ", val).strip().rstrip(",")
            accum["shadows"][normalized] += 1


# ---------- HTML scanning ----------

def extract_html_artifacts(html: str, base_url: str, accum: dict, stylesheet_urls: set):
    soup = BeautifulSoup(html, "html.parser")

    for meta in soup.find_all("meta", attrs={"name": re.compile(r"theme-color", re.I)}):
        content = (meta.get("content") or "").strip()
        for c in find_colors(content):
            accum["theme_colors"][c] += 1

    for link in soup.find_all("link", rel=True):
        rels = {r.lower() for r in link.get("rel", [])}
        href = link.get("href", "").strip()
        if not href:
            continue
        abs_href = urljoin(base_url, href)
        if rels & {"icon", "shortcut icon", "apple-touch-icon", "mask-icon"}:
            accum["favicons"].add(abs_href)
        if "stylesheet" in rels:
            if "fonts.googleapis.com" in abs_href or "fonts.bunny.net" in abs_href or "use.typekit" in abs_href:
                accum["webfont_links"].add(abs_href)
            else:
                stylesheet_urls.add(abs_href)

    for style in soup.find_all("style"):
        css = style.string or "".join(style.strings)
        if css:
            parse_css(css, accum)

    # Inline style="..." attributes
    for el in soup.find_all(style=True):
        inline = el.get("style", "")
        # Fake a rule so DECL_RE matches.
        parse_css("{" + inline + "}", accum)


# ---------- top-level analysis ----------

NOISE_CSS_HINTS = (
    "fontawesome", "font-awesome", "dashicons", "genericons",
    "animate.min", "animate.css", "captcha", "recaptcha",
    "tablepress", "formcraft", "megamenu", "wp-includes",
    "swiper", "slick", "lightbox", "magnific",
)


def is_noise_stylesheet(url: str) -> bool:
    low = url.lower()
    return any(hint in low for hint in NOISE_CSS_HINTS)


# Selector substrings whose rule bodies we drop before tallying colours.
# These all carry STOCK colour values that ship with the platform
# regardless of whether the brand actually uses them — Gutenberg's
# block-library presets are in every WordPress site's CSS even when
# the brand never wears that colour. Counting them gives sites
# entirely the wrong palette.
NOISE_SELECTOR_HINTS = (
    # Gutenberg preset utility classes — .has-vivid-green-cyan-color,
    # .has-pale-pink-background-color, .has-luminous-vivid-orange-color,
    # .has-light-green-cyan-color, .has-cyan-bluish-gray-color, the
    # full preset palette. The corresponding gradient classes too.
    ".has-vivid-",
    ".has-pale-",
    ".has-luminous-",
    ".has-light-green-",
    ".has-cyan-",
    ".has-bluish-",
    ".has-magenta-",
    ".has-gradient",
    # Gutenberg block-library scoped rules — block-internal preset
    # decoration that bleeds into the tally on theme-bundled CSS.
    ".wp-block-cover-",
    ".wp-block-cover ",
    ".wp-block-button__link",
    # Some themes inline tailwind / utility classes that ship with
    # full palettes (--tw-, ...) — covered when those vars are used
    # rather than declared, but worth filtering when seen literally.
    "--tw-",
    "--wp--preset--",
)

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.MULTILINE)


def strip_noise_rules(css_text: str) -> str:
    """Drop CSS rules whose selectors look like Gutenberg / WordPress
    preset noise. These ship in every WP-powered site whether or not
    the brand actually wears those colours.

    Limitation: this is a flat regex, so rules nested inside @media or
    @supports blocks aren't pre-filtered. Most preset declarations sit
    at the top level so we catch the bulk of the noise."""
    def keep(match: re.Match) -> str:
        selector = match.group(1).lower()
        for hint in NOISE_SELECTOR_HINTS:
            if hint in selector:
                return ""  # drop the whole rule
        return match.group(0)
    return _RULE_RE.sub(keep, css_text)


def fetch_stylesheets(urls: set, session: requests.Session, timeout: int,
                       skip_noise: bool):
    for url in sorted(urls):
        if skip_noise and is_noise_stylesheet(url):
            print(f"[skip-noise] {url}", file=sys.stderr)
            continue
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            print(f"[skip-css] {url}: {exc}", file=sys.stderr)
            continue
        if resp.status_code >= 400:
            print(f"[skip-css] {url}: HTTP {resp.status_code}", file=sys.stderr)
            continue
        print(f"[css]  {url}", file=sys.stderr)
        yield url, resp.text


def parse_webfont_links(urls: set) -> list[str]:
    """Extract font family names from Google Fonts (and similar) URLs."""
    families: list[str] = []
    for url in urls:
        qs = unquote(urlparse(url).query)
        for chunk in qs.split("&"):
            if not chunk.lower().startswith("family="):
                continue
            value = chunk.split("=", 1)[1]
            # Both legacy pipe-separated (?family=A|B|C) and modern (&family=A&family=B)
            for fam in re.split(r"[|]", value):
                name = fam.split(":")[0].replace("+", " ").strip()
                if name:
                    families.append(name)
    return families


def top(counter: Counter, n: int = 15):
    return [{"value": v, "count": c} for v, c in counter.most_common(n)]


def infer_spacing_base(spacing_counter: Counter) -> dict:
    """Try to find a base spacing unit (4 or 8 px) by checking which divisor best fits the data."""
    px_values: list[int] = []
    for value, count in spacing_counter.items():
        m = re.match(r"^(\d+)px$", value)
        if not m:
            continue
        n = int(m.group(1))
        if 0 < n <= 256:
            px_values.extend([n] * count)
    if not px_values:
        return {"base_unit": None, "candidates": [], "suggested_scale": []}

    scores = {}
    for base in (4, 6, 8, 10, 12, 16):
        scores[base] = sum(1 for v in px_values if v % base == 0) / len(px_values)
    best = max(scores, key=scores.get)
    suggested = [0, best, best * 2, best * 3, best * 4, best * 6, best * 8, best * 12, best * 16]
    return {
        "base_unit": f"{best}px",
        "base_unit_score": round(scores[best], 3),
        "scale_candidates": {f"{b}px": round(s, 3) for b, s in scores.items()},
        "suggested_scale": [f"{v}px" for v in suggested],
    }


def aggregate_from_pages(pages, *, timeout: int, user_agent: str,
                          skip_noise: bool, start_url: str | None = None):
    """Process pre-crawled pages, fetch their stylesheets, return the style section."""
    accum = {
        "colors": Counter(),
        "colors_by_context": defaultdict(Counter),
        "fonts": Counter(),
        "font_generic": Counter(),
        "icon_fonts": Counter(),
        "font_sizes": Counter(),
        "font_weights": Counter(),
        "line_heights": Counter(),
        "letter_spacings": Counter(),
        "border_radii": Counter(),
        "spacing": Counter(),
        "shadows": Counter(),
        "theme_colors": Counter(),
        "favicons": set(),
        "webfont_links": set(),
        "font_face": defaultdict(set),
    }
    stylesheet_urls: set[str] = set()
    pages_seen = 0

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    for page_url, final_url, html, _root in pages:
        pages_seen += 1
        extract_html_artifacts(html, final_url, accum, stylesheet_urls)

    used_stylesheets = []
    for css_url, css_text in fetch_stylesheets(stylesheet_urls, session, timeout, skip_noise):
        parse_css(css_text, accum)
        used_stylesheets.append(css_url)

    # Brand color heuristic: most-used non-grayscale background color wins.
    # Falls back to overall non-grayscale top.
    bg_colored = [(c, n) for c, n in accum["colors_by_context"]["background"].most_common()
                  if not is_grayscale(c)]
    overall_colored = [(c, n) for c, n in accum["colors"].most_common() if not is_grayscale(c)]
    overall_gray = [(c, n) for c, n in accum["colors"].most_common() if is_grayscale(c)]
    primary_color = bg_colored[0][0] if bg_colored else (overall_colored[0][0] if overall_colored else None)
    secondary_color = bg_colored[1][0] if len(bg_colored) > 1 else None

    # Primary/secondary font: top two non-generic
    fonts_ranked = accum["fonts"].most_common()
    primary_font = fonts_ranked[0][0] if fonts_ranked else None
    secondary_font = fonts_ranked[1][0] if len(fonts_ranked) > 1 else None

    webfont_families = parse_webfont_links(accum["webfont_links"])

    design_tokens = None
    if primary_color:
        design_tokens = {
            "palettes": {
                "primary": tint_shade_palette(primary_color),
            },
            "harmonies": {
                "primary": color_harmonies(primary_color),
            },
            "gradients": gradient_suite(primary_color, secondary_color),
            "contrast": {
                "primary": contrast_report(primary_color),
            },
            "semantic_suggestions": semantic_suggestions(primary_color),
        }
        if secondary_color:
            design_tokens["palettes"]["secondary"] = tint_shade_palette(secondary_color)
            design_tokens["harmonies"]["secondary"] = color_harmonies(secondary_color)
            design_tokens["contrast"]["secondary"] = contrast_report(secondary_color)

    return {
        "domain": urlparse(start_url).netloc if start_url else None,
        "pages_analysed": pages_seen,
        "stylesheets_analysed": sorted(used_stylesheets),
        "stylesheets_skipped_as_noise": sorted(
            url for url in stylesheet_urls if skip_noise and is_noise_stylesheet(url)
        ),
        "brand": {
            "primary_color": primary_color,
            "secondary_color": secondary_color,
            "theme_colors": top(accum["theme_colors"], 5),
            "favicons": sorted(accum["favicons"]),
        },
        "design_tokens": design_tokens,
        "colors": {
            "palette": top(accum["colors"], 20),
            "non_grayscale": [{"value": c, "count": n} for c, n in overall_colored[:15]],
            "grayscale": [{"value": c, "count": n} for c, n in overall_gray[:10]],
            "text": top(accum["colors_by_context"]["text"], 8),
            "background": top(accum["colors_by_context"]["background"], 8),
            "border": top(accum["colors_by_context"]["border"], 8),
        },
        "typography": {
            "primary_font": primary_font,
            "secondary_font": secondary_font,
            "fonts": top(accum["fonts"], 15),
            "generic_fallbacks": top(accum["font_generic"], 6),
            "font_sizes": top(accum["font_sizes"], 20),
            "font_weights": top(accum["font_weights"], 10),
            "line_heights": top(accum["line_heights"], 10),
            "letter_spacings": top(accum["letter_spacings"], 6),
            "webfont_links": sorted(accum["webfont_links"]),
            "webfont_families": sorted(set(webfont_families)),
            "self_hosted_fonts": {
                family: sorted(src for src in srcs if src)
                for family, srcs in accum["font_face"].items()
            },
            "icon_fonts": top(accum["icon_fonts"], 10),
        },
        "shape_language": {
            "border_radii": top(accum["border_radii"], 12),
        },
        "spacing": {
            "common_values": top(accum["spacing"], 20),
            **infer_spacing_base(accum["spacing"]),
        },
        "shadows": {
            "palette": top(accum["shadows"], 12),
        },
        "social_media_ad_specs": SOCIAL_MEDIA_AD_SPECS,
    }


def analyze(start_url: str, max_pages: int, timeout: int, user_agent: str,
            skip_noise: bool):
    return aggregate_from_pages(
        iter_pages(start_url, max_pages, timeout, user_agent),
        timeout=timeout, user_agent=user_agent,
        skip_noise=skip_noise, start_url=start_url,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Starting URL (e.g. https://example.com)")
    parser.add_argument("-o", "--output", default="style.yaml", help="Output YAML file")
    parser.add_argument("--max-pages", type=int, default=50,
                        help="Max pages to scan for stylesheet/meta references (default 50 — design facts saturate quickly).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    parser.add_argument(
        "--include-plugin-css",
        action="store_true",
        help="Include known-noise plugin stylesheets (animate.css, FontAwesome, formcraft, etc.). Default skips them.",
    )
    args = parser.parse_args()

    result = analyze(
        args.url, args.max_pages, args.timeout, args.user_agent,
        skip_noise=not args.include_plugin_css,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, allow_unicode=True, width=120)

    brand = result["brand"]
    typ = result["typography"]
    print(
        f"Analysed {result['pages_analysed']} pages, "
        f"{len(result['stylesheets_analysed'])} stylesheets. "
        f"Primary color: {brand['primary_color']}, "
        f"primary font: {typ['primary_font']}. "
        f"Wrote {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
