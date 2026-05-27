#!/usr/bin/env python3
"""Use Amazon Bedrock (Anthropic Claude vision) to read a brand's identity from screenshots.

The model is shown one or more screenshots of the live site plus DOM hints (from
the Playwright probe), and returns strict JSON describing the visible brand
colours, fonts, and tone — closer to a designer's perception than CSS frequency.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import boto3

DEFAULT_REGION = (
    os.environ.get("AWS_REGION")
    or os.environ.get("AWS_DEFAULT_REGION")
    or "us-east-1"
)

# Bedrock cross-region inference profile IDs. Verified ACTIVE 2026-05 via
# `aws bedrock list-inference-profiles`. Note: Sonnet 4.6 / Opus 4.7 profile IDs
# dropped the `-YYYYMMDD-v1:0` suffix the earlier Anthropic models used — using
# the old format here yields ValidationException("model identifier is invalid").
# Default to Opus 4.7 (latest, best quality for brand vision + content analysis).
DEFAULT_MODELS = {
    "us": "us.anthropic.claude-opus-4-7",
    "eu": "eu.anthropic.claude-opus-4-7",
    "ap": "apac.anthropic.claude-opus-4-7",
}


def _default_model_for_region(region: str) -> str:
    if region.startswith("eu-"):
        return DEFAULT_MODELS["eu"]
    if region.startswith("ap-"):
        return DEFAULT_MODELS["ap"]
    return DEFAULT_MODELS["us"]


PROMPT = """You are looking at one or more screenshots of a brand's live website.
Extract the brand identity exactly as a designer would perceive it on screen —
not from CSS, but from what is visually dominant and meaningful.

DOM HINTS (collected from computed styles — these are noisy and may be wrong;
use as cross-reference only):
{dom_hints_json}

Return STRICT JSON with this shape and nothing else. Do not wrap in markdown
fences. Do not add commentary outside the JSON.

{{
  "primary_color": "#RRGGBB",
  "secondary_color": "#RRGGBB",
  "accent_color": "#RRGGBB",
  "surface_color": "#RRGGBB",
  "text_color": "#RRGGBB",
  "display_font_guess": "string",
  "body_font_guess": "string",
  "tone_words": ["word", "word", "word"],
  "color_names": {{
    "primary": "Two Word Name",
    "secondary": "Two Word Name",
    "accent": "Two Word Name",
    "surface": "Two Word Name",
    "text": "Two Word Name"
  }},
  "notes": "1-2 sentences on the visual identity"
}}

Rules:
- Use only colours that are clearly visible in the screenshots.
- "secondary" must be a real brand colour, never a near-white surface like #F5F5F5.
- "accent" is a sparing highlight (warnings, calls-to-attention), not a duplicate of primary.
- "surface" is the page/panel background you see most often.
- "color_names" should be evocative two-word names (e.g. "Atmosphere", "Ultra Green", "Peach Fury").
- If a DOM hint matches what you see, prefer it. If it disagrees with the screenshot, trust the screenshot.
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # strip ```json … ``` fencing if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # otherwise grab the first {...} block
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def _resolve_model_and_region(model_id: str | None, region: str | None) -> tuple[str, str]:
    region = region or DEFAULT_REGION
    model_id = (
        model_id
        or os.environ.get("BEDROCK_MODEL_ID")
        or _default_model_for_region(region)
    )
    return model_id, region


def _invoke(
    *,
    content: list[dict[str, Any]],
    model_id: str,
    region: str,
    max_tokens: int,
    label: str,
) -> dict[str, Any]:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    client = boto3.client("bedrock-runtime", region_name=region)
    n_images = sum(1 for c in content if c.get("type") == "image")
    print(f"  bedrock[{label}]: {model_id} in {region} ({n_images} image(s))", file=sys.stderr)
    resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    )
    return _extract_json(text)


def _image_block(path: str) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) > 5 * 1024 * 1024:
        raise ValueError(
            f"{path} is {len(data)} bytes — Bedrock caps images at 5 MB. "
            "Pass the above-the-fold shot only, or resize first."
        )
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def analyze_screenshots(
    screenshot_paths: list[str],
    *,
    dom_hints: dict | None = None,
    model_id: str | None = None,
    region: str | None = None,
    max_tokens: int = 1500,
) -> dict[str, Any]:
    """Send screenshots to Bedrock and return the parsed brand JSON."""
    if not screenshot_paths:
        raise ValueError("at least one screenshot required")

    model_id, region = _resolve_model_and_region(model_id, region)

    content: list[dict[str, Any]] = [_image_block(p) for p in screenshot_paths]
    content.append(
        {
            "type": "text",
            "text": PROMPT.format(dom_hints_json=json.dumps(dom_hints or {}, indent=2)),
        }
    )

    return _invoke(
        content=content,
        model_id=model_id,
        region=region,
        max_tokens=max_tokens,
        label="identity",
    )


CLASSIFY_PROMPT = """You are looking at the homepage screenshot of a single brand's website.
Below is a list of every image URL the crawler tagged as a possible logo or
header asset. Your job: decide for each URL which of these four categories it
falls into.

CATEGORIES
- "brand_primary"    The actual primary logo of THIS website's owner (the brand
                     whose homepage you're looking at). There is usually exactly
                     one of these — the mark in the header.
- "brand_supporting" Trust marks, badges, accreditations, awards, or experience
                     claims that belong to THIS brand. Examples: "Over 20 Years
                     Experience" badge, ISO certifications, industry awards,
                     "Established 1990" lockups, environment-agency licences.
- "customer_logo"    Logos of OTHER companies the brand serves as customers /
                     clients / partners. These appear in "trusted by" strips,
                     case-study grids, or partner lists. They look like real
                     external brand logos.
- "irrelevant"       Anything else (UI icons, decorative graphics, photos
                     misclassified as logos, social-media share icons).

DOMAIN: {domain}
CANDIDATE URLS:
{url_list}

For each URL return a classification AND a one-line description of what you
believe the image is. For supporting marks try to describe the claim or
accreditation ("Over 20 Years Experience badge", "ISO 9001 certified").

Return STRICT JSON with this shape and nothing else, no markdown fences:

{{
  "classifications": [
    {{
      "url": "<full url from the list>",
      "category": "brand_primary | brand_supporting | customer_logo | irrelevant",
      "description": "short human description"
    }}
  ],
  "notes": "1-2 sentences describing the supporting marks/badges you can SEE on the homepage screenshot (so the next pass can hunt them down even if the URL list is incomplete)"
}}

Rules:
- Use the screenshot as primary evidence. Filenames lie.
- A logo that appears in the page header, large and prominently, is usually
  brand_primary. A logo that sits in a partner-strip carousel is customer_logo.
- If a URL appears in the list but you can't see it on the homepage, infer from
  filename + domain. Default to "customer_logo" only when the filename pattern
  matches a known external brand or a partner-strip path.
- Every URL in CANDIDATE URLS must appear exactly once in classifications.
"""


def _fetch_image_bytes(url: str, timeout: int = 10) -> bytes | None:
    """Fetch an image URL. Returns None on any failure or non-image content."""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "brand-guidelines/1.0"})
        if not r.ok or not r.content:
            return None
        ctype = (r.headers.get("Content-Type") or "").lower()
        if not (ctype.startswith("image/") or ctype == ""):
            return None
        return r.content
    except Exception:
        return None


def _guess_media_type(data: bytes, url: str) -> str:
    """Sniff a media_type Bedrock will accept (png/jpeg/gif/webp)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # Fall back on extension
    low = url.lower().rsplit(".", 1)[-1]
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp",
    }.get(low, "image/png")


def classify_brand_assets(
    screenshot_paths: list[str],
    candidate_urls: list[str],
    *,
    domain: str,
    inline_urls: list[str] | None = None,
    model_id: str | None = None,
    region: str | None = None,
    max_tokens: int = 3000,
) -> dict[str, Any]:
    """Ask Bedrock to triage which 'logo' URLs are this brand vs. someone else's.

    `inline_urls` is a subset of `candidate_urls` whose image bytes should be
    fetched and embedded as vision inputs (essential for things like favicons
    where the filename is uninformative — Bedrock can't tell "Over 20 Years
    Experience" badge from a UI icon without seeing the pixels).
    """
    if not screenshot_paths:
        raise ValueError("at least one screenshot required")
    if not candidate_urls:
        return {"classifications": [], "notes": ""}

    model_id, region = _resolve_model_and_region(model_id, region)

    content: list[dict[str, Any]] = [_image_block(p) for p in screenshot_paths]

    inline_set = set(inline_urls or [])
    inline_block_pairs: list[tuple[str, dict[str, Any]]] = []
    for url in candidate_urls:
        if url not in inline_set:
            continue
        data = _fetch_image_bytes(url)
        if not data or len(data) > 4 * 1024 * 1024:
            continue
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _guess_media_type(data, url),
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
        inline_block_pairs.append((url, block))

    # Interleave: explanatory text label + the image, for each inline asset.
    # This makes the URL→image association unambiguous in the model's view.
    if inline_block_pairs:
        content.append(
            {
                "type": "text",
                "text": (
                    "Below are the actual pixel contents of some candidate URLs. "
                    "Use these directly when deciding the category — do not rely "
                    "on the filename for these."
                ),
            }
        )
        for url, block in inline_block_pairs:
            content.append({"type": "text", "text": f"Image for URL: {url}"})
            content.append(block)

    url_list = "\n".join(f"- {u}" for u in candidate_urls)
    content.append(
        {
            "type": "text",
            "text": CLASSIFY_PROMPT.format(domain=domain, url_list=url_list),
        }
    )

    return _invoke(
        content=content,
        model_id=model_id,
        region=region,
        max_tokens=max_tokens,
        label="assets",
    )


ESSENCE_PROMPT = """You are a brand strategist. Below is everything the crawler
extracted from a single company's website: every page title, plus a sampling
of body paragraphs. Distil this into the brand's strategic essence — the kind
of thing that would anchor a brand guidelines book.

DOMAIN: {domain}

PAGE TITLES (full set, gives the service taxonomy):
{titles}

PARAGRAPH SAMPLE (representative copy from across the site):
{paragraphs}

Return STRICT JSON, no markdown fences:

{{
  "mission_statement": "One sentence in the brand's own voice — what they exist to do, who they do it for. Keep it crisp and quotable. 15-30 words.",
  "value_propositions": [
    "3-4 short noun phrases capturing what makes them different (e.g. 'Same-day collection', 'Fully licensed waste carrier', 'Local family-run since 1990')."
  ],
  "core_services": [
    {{
      "name": "Service name (Title Case, 1-3 words)",
      "description": "One sentence — what the service is and who it's for. Around 15-25 words."
    }}
  ],
  "key_strengths": [
    "4-6 single-line strengths the company emphasises about itself. Quote concrete claims where present ('over 20 years experience', 'fully licensed by the Environment Agency'). Avoid generic words like 'professional' or 'quality'."
  ],
  "tone_of_voice": "1-2 sentences on how the copy reads — formal/informal, technical/plainspoken, regional/national, etc.",
  "contact_details": {{
    "phone": "primary phone number as written on the site, or null",
    "email": "primary email address, or null",
    "address": "full postal address on one line, or null",
    "hours": "opening hours as written, or null",
    "social_links": ["full URLs to the brand's social-media profiles found in the copy"]
  }}
}}

Rules:
- Use the brand's own language and concrete claims wherever possible. Don't
  invent stats or accreditations that aren't in the source text.
- If multiple page titles describe variants of one service (different skip
  sizes, different waste types), collapse them into ONE core_service entry.
- core_services should describe what the company OFFERS, not blog topics.
- key_strengths should be facts the buyer would care about, not adjectives.
- For contact_details: pull verbatim from the source text. If a field is not
  mentioned, return null (not a placeholder). Phone numbers should be exactly
  as displayed, including spaces. Do not invent.
"""


def extract_brand_essence(
    *,
    domain: str,
    page_titles: list[str],
    paragraphs: list[str],
    model_id: str | None = None,
    region: str | None = None,
    max_tokens: int = 2500,
    max_paragraph_chars: int = 18000,
) -> dict[str, Any]:
    """Text-only Bedrock call: distil mission, services, strengths from the copy."""
    model_id, region = _resolve_model_and_region(model_id, region)

    titles_block = "\n".join(f"- {t}" for t in page_titles if t)
    # Pack paragraphs up to the char budget, longest first (signal-richer).
    ordered = sorted({p for p in paragraphs if p}, key=len, reverse=True)
    buf: list[str] = []
    used = 0
    for p in ordered:
        if used + len(p) + 2 > max_paragraph_chars:
            continue
        buf.append(p)
        used += len(p) + 2
    paragraphs_block = "\n\n".join(buf)

    content = [
        {
            "type": "text",
            "text": ESSENCE_PROMPT.format(
                domain=domain,
                titles=titles_block or "(none)",
                paragraphs=paragraphs_block or "(none)",
            ),
        }
    ]

    return _invoke(
        content=content,
        model_id=model_id,
        region=region,
        max_tokens=max_tokens,
        label="essence",
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshots", nargs="+", help="PNG screenshot paths")
    parser.add_argument("--dom-hints", help="Path to a JSON file of DOM hints")
    parser.add_argument("--model")
    parser.add_argument("--region")
    args = parser.parse_args()

    hints = None
    if args.dom_hints:
        hints = json.loads(Path(args.dom_hints).read_text(encoding="utf-8"))

    result = analyze_screenshots(
        args.screenshots,
        dom_hints=hints,
        model_id=args.model,
        region=args.region,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
