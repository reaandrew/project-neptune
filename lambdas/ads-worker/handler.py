"""Lambda entrypoint for project-neptune-ads-worker.

Invoked asynchronously by ads-create. Event shape:
    {
      "adId":        "<uuid>",
      "brandJobId":  "<existing brand-jobs id>",
      "headline":    "...",     # optional
      "body":        "...",     # optional
      "cta":         "...",     # optional
      "sampleAdUrl": "...",     # optional style-reference URL
      # Creative-brief dimensions — all optional; empty == auto:
      "platform":   "facebook-feed",
      "objective":  "get-leads",
      "layout":     "single-hero",
      "angle":      "benefit-led",
      "elements":   ["logo","headline","cta","website"]
    }

Pipeline:
  1. Load the brand.yaml + the brand-guidelines PDF + the brand-primary
     logo from the artifacts bucket using brandJobId.
  2. Upload the PDF to OpenAI Files so gpt-4o can actually read the
     document (typography page, colour swatches, mission, etc.).
  3. Ask gpt-4o for a JSON {headline, body, cta, image_prompt}:
       - empty user-supplied fields are filled in from the brand context,
       - any supplied fields are kept verbatim,
       - image_prompt is a detailed brief for gpt-image-1 that quotes
         the final headline/body/cta as literal text the renderer must
         spell exactly.
  4. Call gpt-image-1 via images.edit with the brand-primary logo PNG
     as a reference image so the model has the actual pixels to draw
     from instead of guessing from a URL.
  5. Upload PNG + the resolved copy to S3 + DDB.

The OPENAI_API_KEY is read once per cold start from SSM SecureString
parameter /project-neptune/openai-api-key.
"""

from __future__ import annotations

import base64
import io
import json
import os
import random
import sys
import time
import traceback
import urllib.request

import boto3
import yaml


# ─────────────────────────────────────────────────────────────────────
# Creative-brief dimension lookups. Kept in sync with the frontend
# selects in BrandJobDetailPage.tsx + Ad-Prompt static UI. Worker uses
# the human label in the prompt sent to gpt-4o, not the slug.
# ─────────────────────────────────────────────────────────────────────
PLATFORM_LABELS = {
    "facebook-feed": "Facebook feed",
    "instagram-feed": "Instagram feed",
    "instagram-story": "Instagram story",
    "linkedin-post": "LinkedIn post",
    "tiktok-reel": "TikTok / Reel cover",
    "google-display": "Google display ad",
    "website-banner": "Website banner",
    "email-header": "Email header",
    "print-flyer": "Print flyer",
    "multi-platform": "Multi-platform pack",
}
OBJECTIVE_LABELS = {
    "brand-awareness": "Brand awareness",
    "get-leads": "Get leads",
    "promote-service": "Promote a service",
    "promote-product": "Promote a product",
    "promote-offer": "Promote an offer",
    "drive-traffic": "Drive website traffic",
    "book-appointments": "Book appointments",
    "promote-event": "Promote an event",
    "build-trust": "Build trust / social proof",
    "recruitment": "Recruitment",
}
LAYOUT_LABELS = {
    "single-hero": "Single hero image",
    "full-image-overlay": "Full image with text overlay",
    "split-image-text": "Split image and text",
    "grid-collage": "Grid / collage",
    "product-card": "Product card",
    "service-card": "Service card",
    "offer-card": "Offer card",
    "testimonial-card": "Testimonial card",
    "before-after": "Before-and-after",
    "carousel-sequence": "Carousel sequence (first frame)",
}
ANGLE_LABELS = {
    "benefit-led": "Benefit-led — what the buyer gains, in their words",
    "problem-solution": "Problem / solution — name the friction, then resolve it",
    "trust-led": "Trust-led — credentials, accreditations, scale, years",
    "local-expertise": "Local expertise — place names and regional pride",
    "offer-led": "Offer-led — the deal is the hero",
    "seasonal": "Seasonal — time-bound hook tied to the calendar",
    "educational": "Educational — teach something the reader will thank you for",
    "testimonial-led": "Testimonial-led — a real customer's voice is the hero",
    "premium-quality": "Premium quality — restraint, generous whitespace, single hero element",
    "urgency-limited": "Urgency / limited time — countdown energy without shouting",
}
ELEMENT_LABELS = {
    "logo": "Logo",
    "headline": "Headline",
    "subheadline": "Subheadline",
    "body": "Body copy",
    "cta": "CTA button",
    "website": "Website",
    "phone": "Phone number",
    "email": "Email",
    "social": "Social handle",
    "offer-badge": "Offer badge",
    "star-rating": "Star rating",
    "testimonial": "Testimonial",
    "price": "Price",
    "qr-code": "QR code",
    "location": "Location",
    "legal": "Legal disclaimer",
}
DEFAULT_ELEMENTS = ["logo", "headline", "cta", "website"]


def _resolve_dimension(value: str, label_map: dict[str, str]) -> tuple[str, bool]:
    """Return (human_label, was_auto). If value is empty or unknown,
    pick a random key from the map."""
    if value and value in label_map:
        return label_map[value], False
    pick = random.choice(list(label_map.keys()))
    return label_map[pick], True

ARTIFACTS_BUCKET = os.environ["ARTIFACTS_BUCKET"]
ADS_JOBS_TABLE = os.environ["ADS_JOBS_TABLE"]
OPENAI_API_KEY_PARAM = os.environ.get(
    "OPENAI_API_KEY_PARAM", "/project-neptune/openai-api-key"
)
TEXT_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-5")
IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_SIZE = os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024")
IMAGE_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "high")

_ddb = boto3.client("dynamodb")
_s3 = boto3.client("s3")
_ssm = boto3.client("ssm")

_openai_client = None


def _openai():
    global _openai_client
    if _openai_client is None:
        out = _ssm.get_parameter(Name=OPENAI_API_KEY_PARAM, WithDecryption=True)
        from openai import OpenAI
        _openai_client = OpenAI(api_key=out["Parameter"]["Value"])
    return _openai_client


# ─────────────────────────────────────────────────────────────────────
# DynamoDB
# ─────────────────────────────────────────────────────────────────────
def _set_status(ad_id: str, status: str, **extra: str) -> None:
    expr_names = {"#s": "status"}
    expr_values = {":s": {"S": status}}
    sets = ["#s = :s"]
    for k, v in extra.items():
        if v is None:
            continue
        expr_names[f"#{k}"] = k
        expr_values[f":{k}"] = {"S": str(v)}
        sets.append(f"#{k} = :{k}")
    _ddb.update_item(
        TableName=ADS_JOBS_TABLE,
        Key={"ad_id": {"S": ad_id}},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


# ─────────────────────────────────────────────────────────────────────
# System prompt — verbatim per project owner
# ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "Create a branded Facebook advert image using the attached brand "
    "guidelines as the sole reference for the brand identity. This is an "
    "image creation task: generate a finished promotional advert image, "
    "not just a concept or text layout. Use the exact approved company "
    "logo from the attached brand guidelines or supplied logo asset. Do "
    "not redesign, recreate, restyle, approximate, or invent a new logo. "
    "The logo must match the official brand exactly in wording, "
    "proportions, colours, spacing, and overall appearance.\n\n"
    "Follow the brand guidelines closely for logo usage, colour palette, "
    "typography, tone of voice, and visual style. Use real contextual "
    "photography relevant to the business, and where appropriate, "
    "realistically superimpose the exact official company logo onto "
    "elements within the image such as signage, products, packaging, "
    "vehicles, uniforms, equipment, or other real-world surfaces. The "
    "logo should appear naturally integrated into the scene while "
    "remaining fully accurate to the original brand asset.\n\n"
    "Include a clear headline, concise supporting copy, key brand or "
    "trust messages, and a strong call to action, all styled in line "
    "with the attached brand guidelines. The final output should be a "
    "polished, professional, on-brand Facebook advert image. If the "
    "exact logo cannot be clearly reproduced from the attached "
    "guidelines, use a clearly marked placeholder such as 'Insert "
    "official logo here' instead of inventing a new one.\n\n"
    "Render the photographic elements in a photorealistic style — they "
    "should look like real photographs, not illustrations or 3D renders."
)


COPY_INSTRUCTIONS = """
You will receive: (a) a JSON brand summary (including a
`marketing_imagery` list of real photos pulled from the brand's
site, each with a category and description), (b) the brand-
guidelines PDF as an attached file, (c) optionally a sample-ad image
as a style cue, (d) optionally user-supplied headline/body/CTA.

Reply with EXACTLY this JSON object — no markdown, no commentary:

  {
    "headline":            "<a strong short headline, max 6 words>",
    "body":                "<1-2 sentence supporting copy>",
    "cta":                 "<2-4 word call to action>",
    "reference_image_url": "<the url field of the best photo from "
                           "brand_summary.marketing_imagery, or empty "
                           "string if none fit the concept>",
    "image_prompt":        "<a single detailed prompt for gpt-image-1>"
  }

Rules:
- The CREATIVE BRIEF (PLATFORM / OBJECTIVE / LAYOUT / MESSAGE /
  ELEMENTS) is the operator's choices and the image_prompt MUST
  reflect them:
    * PLATFORM controls aspect, safe zones and idiom. A LinkedIn
      post reads as professional; an Instagram story is vertical
      9:16 with bold typography; a print flyer reads as A4 portrait
      with crisp typesetting; etc.
    * OBJECTIVE controls structure. Lead-gen → foreground the offer
      + CTA. Brand-awareness → foreground tone, logo, hero imagery.
      Testimonial / build-trust → foreground a quote + attribution.
      Recruitment → foreground people-led photography.
    * LAYOUT is non-negotiable. Apply it verbatim: a 'Single hero
      image' is a full-bleed photo with minimal overlay; a 'Split
      image and text' is a 50/50 split; a 'Testimonial card' is a
      centred card on a soft brand-coloured background; etc.
    * MESSAGE is the copy direction. Match the headline's emotional
      hook to it.
    * ELEMENTS controls which on-image text/graphic items appear.
      ONLY render the elements listed. If 'Phone number' is in the
      list, render the brand's phone from contact_details. If it's
      not in the list, do NOT render contact details.
- If the user supplied any of headline/body/cta, copy them VERBATIM
  into the JSON (don't paraphrase). Fill the rest from the brand
  context — tone, mission, services, audience.
- For `reference_image_url`: pick the marketing_imagery entry whose
  `category` + `description` best matches the concept of the
  headline/CTA. Prefer 'lifestyle' or 'context' for service-led ads,
  'product' for product-led ads. Return the EXACT url string from
  the list. If no entry is genuinely a good fit, return "" (empty).
- The image_prompt must instruct gpt-image-1 to render:
    * the headline as LITERAL TEXT, spelled exactly the same;
    * the supporting copy as LITERAL TEXT;
    * the CTA as LITERAL TEXT inside a button or pill;
    * the brand's exact registered name as LITERAL TEXT — never
      paraphrase or restyle it;
    * realistic photographic elements relevant to the business;
    * the brand's colour palette (state the primary + secondary hex
      values directly in the prompt);
    * a 1024x1024 Facebook-ready square composition.
- If you chose a reference_image_url, instruct gpt-image-1 to
  reproduce that scene faithfully — same setting, same lighting,
  same subjects — but redrawn to fit the advert layout. Describe
  the scene IN the image_prompt so the renderer has context even
  if the reference image is lost in transit.
- DO NOT invent a logo design. The renderer will receive the official
  logo PNG as a reference image — instruct it to reproduce that exact
  logo (matching the proportions and wordmark in the reference) in the
  top-left at about 18% of the canvas width.
- If a sample-ad style cue was supplied, mention layout characteristics
  from it (split layout, badge in corner, etc.) but always defer to
  the brand colours and typography.
"""


# ─────────────────────────────────────────────────────────────────────
# Brand-context helpers
# ─────────────────────────────────────────────────────────────────────
def _brand_summary(brand: dict) -> dict:
    style = brand.get("style") or {}
    brand_id = style.get("brand") or {}
    typo = style.get("typography") or {}
    content = brand.get("content") or {}
    essence = content.get("essence") or {}
    images_block = brand.get("images") or {}
    images = images_block.get("images") or []

    primary_logo = next(
        (im.get("url") for im in images if im.get("role") == "brand_primary"),
        None,
    ) or next(
        (im.get("url") for im in images if im.get("role") == "logo"),
        None,
    )
    favicons = brand_id.get("favicons") or []
    brand_name = (
        essence.get("brand_name")
        or brand_id.get("brand_name")
        or brand.get("domain")
    )

    # Marketing imagery — populated by the brand-worker's Bedrock pass.
    # Each item: {url, category, description, subjects}.
    marketing = images_block.get("marketing_imagery") or []

    return {
        "domain": brand.get("domain"),
        "start_url": brand.get("start_url"),
        "brand_name": brand_name,
        "mission_statement": essence.get("mission_statement"),
        "core_services": essence.get("core_services"),
        "key_strengths": essence.get("key_strengths"),
        "tone_words": brand_id.get("tone_words"),
        "primary_color": brand_id.get("primary_color"),
        "secondary_color": brand_id.get("secondary_color"),
        "accent_color": brand_id.get("accent_color"),
        "surface_color": brand_id.get("surface_color"),
        "text_color": brand_id.get("text_color"),
        "primary_font": typo.get("primary_font"),
        "body_font": typo.get("secondary_font"),
        "primary_logo_url": primary_logo,
        "favicon_urls": favicons[:3],
        "contact": essence.get("contact_details"),
        # Cap to the 12 best entries — token usage matters at gpt-5
        # rates and the model only needs a representative sample to
        # choose from.
        "marketing_imagery": marketing[:12],
    }


def _fetch_url(url: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
    """Fetch a URL with a tiny UA, capped size."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "project-neptune-ads-worker/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(max_bytes)


# ─────────────────────────────────────────────────────────────────────
# Step 1 — gpt-4o drafts copy + image prompt
# ─────────────────────────────────────────────────────────────────────
def _draft_copy_and_prompt(
    brand_summary: dict,
    pdf_bytes: bytes | None,
    headline: str,
    body: str,
    cta: str,
    sample_ad_url: str,
    brief: dict,
) -> dict:
    """`brief` is the resolved creative brief — a dict shaped like:
        {
          "platform":  ("Facebook feed", was_auto_bool),
          "objective": ("Get leads",     was_auto_bool),
          "layout":    ("Single hero…",  was_auto_bool),
          "angle":     ("Benefit-led…",  was_auto_bool),
          "elements":  [human_label, ...],
        }
    """
    client = _openai()

    # Attach the brand-guidelines PDF as a file so the text model can
    # actually see the visual brand, not just a flat JSON summary.
    file_id = None
    if pdf_bytes:
        try:
            f = client.files.create(
                file=("brand_guidelines.pdf", pdf_bytes, "application/pdf"),
                purpose="user_data",
            )
            file_id = f.id
        except Exception as e:
            print(f"  ! pdf upload failed ({e}); proceeding without it.", file=sys.stderr)

    # Render the creative brief — auto-picked values get a "(auto)"
    # marker so gpt-4o knows the operator didn't specifically choose.
    def _line(label: str, val: tuple[str, bool]) -> str:
        text, was_auto = val
        return f"  {label}: {text}" + ("  (auto)" if was_auto else "")
    elements_line = ", ".join(brief["elements"]) if brief["elements"] else "(none — image-only composition)"
    creative_brief_text = (
        "CREATIVE BRIEF (operator's choices — adapt the image_prompt to these):\n"
        f"{_line('PLATFORM ', brief['platform'])}\n"
        f"{_line('OBJECTIVE', brief['objective'])}\n"
        f"{_line('LAYOUT   ', brief['layout'])}\n"
        f"{_line('MESSAGE  ', brief['angle'])}\n"
        f"  ELEMENTS : {elements_line}"
    )

    user_content = [
        {
            "type": "text",
            "text": (
                "Brand summary JSON (extracted from the attached "
                f"guidelines PDF):\n{json.dumps(brand_summary, indent=2)}\n\n"
                f"{creative_brief_text}\n\n"
                f"User-supplied headline: {headline or '(blank — invent one)'}\n"
                f"User-supplied body:     {body or '(blank — invent one)'}\n"
                f"User-supplied CTA:      {cta or '(blank — invent one)'}"
            ),
        }
    ]
    if file_id:
        user_content.append({
            "type": "file",
            "file": {"file_id": file_id},
        })
    if sample_ad_url:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": sample_ad_url},
        })

    resp = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + COPY_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"text model returned non-JSON: {raw[:200]}") from e

    for k in ("headline", "body", "cta", "image_prompt"):
        if not parsed.get(k):
            raise RuntimeError(f"text model omitted '{k}': {raw[:200]}")
    return parsed


# ─────────────────────────────────────────────────────────────────────
# Step 2 — gpt-image-1 renders, with logo + (optional) brand photo as
# reference images.
# ─────────────────────────────────────────────────────────────────────
def _render_image(
    prompt: str,
    logo_bytes: bytes | None,
    photo_bytes: bytes | None,
) -> bytes:
    client = _openai()

    refs: list[tuple[str, bytes, str]] = []
    if logo_bytes:
        refs.append(("logo.png", logo_bytes, "image/png"))
    if photo_bytes:
        refs.append(("brand_photo.png", photo_bytes, "image/png"))

    if refs:
        # gpt-image-1's images.edit endpoint accepts a single image or
        # an array; passing both the logo and a brand photo gives the
        # renderer the exact mark plus a true-to-life scene to redraw.
        image_arg = refs[0] if len(refs) == 1 else refs
        resp = client.images.edit(
            model=IMAGE_MODEL,
            image=image_arg,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
    else:
        resp = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
    b64 = resp.data[0].b64_json
    if not b64:
        url = resp.data[0].url
        if not url:
            raise RuntimeError("image model returned neither b64_json nor url")
        return _fetch_url(url)
    return base64.b64decode(b64)


# ─────────────────────────────────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────────────────────────────────
def handler(event, _context):
    ad_id = event["adId"]
    brand_job_id = event["brandJobId"]
    headline = (event.get("headline") or "").strip()
    body = (event.get("body") or "").strip()
    cta = (event.get("cta") or "").strip()
    sample_ad_url = (event.get("sampleAdUrl") or "").strip()

    # ── Resolve the creative brief — auto-pick anything missing. ───
    # We seed Python's RNG with the ad_id so a given job replayed
    # produces the same auto picks (helps when debugging an ad run).
    random.seed(ad_id)
    platform = _resolve_dimension(event.get("platform") or "", PLATFORM_LABELS)
    objective = _resolve_dimension(event.get("objective") or "", OBJECTIVE_LABELS)
    layout = _resolve_dimension(event.get("layout") or "", LAYOUT_LABELS)
    angle = _resolve_dimension(event.get("angle") or "", ANGLE_LABELS)
    raw_elements = event.get("elements") or []
    if not raw_elements:
        raw_elements = list(DEFAULT_ELEMENTS)
    elements_labels = [
        ELEMENT_LABELS[e] for e in raw_elements if e in ELEMENT_LABELS
    ] or [ELEMENT_LABELS[e] for e in DEFAULT_ELEMENTS]
    brief = {
        "platform": platform,
        "objective": objective,
        "layout": layout,
        "angle": angle,
        "elements": elements_labels,
    }

    started_at = str(int(time.time()))
    _set_status(
        ad_id, "running",
        started_at=started_at,
        # Persist the resolved brief so the operator can see what was
        # actually used (especially what got auto-picked).
        resolved_platform=platform[0],
        resolved_objective=objective[0],
        resolved_layout=layout[0],
        resolved_angle=angle[0],
    )

    try:
        # ── 1. Brand context: YAML, PDF, logo ──────────────────────
        yaml_key = f"brand-jobs/{brand_job_id}.yaml"
        try:
            yaml_obj = _s3.get_object(Bucket=ARTIFACTS_BUCKET, Key=yaml_key)
        except Exception as e:
            raise RuntimeError(f"brand yaml not found at s3://{ARTIFACTS_BUCKET}/{yaml_key}: {e}")
        brand_dict = yaml.safe_load(yaml_obj["Body"].read().decode("utf-8"))
        summary = _brand_summary(brand_dict)

        pdf_key = f"brand-jobs/{brand_job_id}.pdf"
        pdf_bytes = None
        try:
            pdf_obj = _s3.get_object(Bucket=ARTIFACTS_BUCKET, Key=pdf_key)
            pdf_bytes = pdf_obj["Body"].read()
            print(f"[ad {ad_id}] loaded pdf ({len(pdf_bytes)} bytes)", file=sys.stderr)
        except Exception as e:
            print(f"[ad {ad_id}] no pdf at {pdf_key} ({e})", file=sys.stderr)

        logo_bytes = None
        logo_url = summary.get("primary_logo_url")
        if logo_url:
            try:
                logo_bytes = _fetch_url(logo_url)
                print(f"[ad {ad_id}] fetched logo from {logo_url} ({len(logo_bytes)} bytes)", file=sys.stderr)
            except Exception as e:
                print(f"[ad {ad_id}] logo fetch failed ({e}); rendering without reference", file=sys.stderr)

        # ── 2. Draft copy + image prompt ───────────────────────────
        drafted = _draft_copy_and_prompt(
            summary, pdf_bytes, headline, body, cta, sample_ad_url, brief,
        )
        ref_url = (drafted.get("reference_image_url") or "").strip()
        print(
            f"[ad {ad_id}] copy: headline={drafted['headline']!r} "
            f"cta={drafted['cta']!r} ref={ref_url or '(none)'}",
            file=sys.stderr,
        )

        # ── 3. Fetch the picked brand photo, if any ────────────────
        photo_bytes = None
        if ref_url:
            # Sanity-check: the model must pick from the supplied list,
            # not invent a URL. Drop it silently if it cheated.
            allowed = {
                it.get("url") for it in (summary.get("marketing_imagery") or [])
                if it.get("url")
            }
            if ref_url in allowed:
                try:
                    photo_bytes = _fetch_url(ref_url)
                    print(
                        f"[ad {ad_id}] fetched brand photo ({len(photo_bytes)} bytes)",
                        file=sys.stderr,
                    )
                except Exception as e:
                    print(f"[ad {ad_id}] brand-photo fetch failed ({e})", file=sys.stderr)
            else:
                print(
                    f"[ad {ad_id}] reference_image_url not in marketing_imagery list — ignoring",
                    file=sys.stderr,
                )

        # ── 4. Render ──────────────────────────────────────────────
        png_bytes = _render_image(drafted["image_prompt"], logo_bytes, photo_bytes)
        print(f"[ad {ad_id}] rendered image ({len(png_bytes)} bytes)", file=sys.stderr)

        # ── 4. Persist ─────────────────────────────────────────────
        image_key = f"ads/{ad_id}.png"
        _s3.put_object(
            Bucket=ARTIFACTS_BUCKET, Key=image_key,
            Body=png_bytes, ContentType="image/png",
        )
        prompt_key = f"ads/{ad_id}.prompt.txt"
        _s3.put_object(
            Bucket=ARTIFACTS_BUCKET, Key=prompt_key,
            Body=drafted["image_prompt"].encode("utf-8"),
            ContentType="text/plain",
        )

        _set_status(
            ad_id, "done",
            image_key=image_key,
            prompt_key=prompt_key,
            headline=drafted["headline"],
            body=drafted["body"],
            cta=drafted["cta"],
            completed_at=str(int(time.time())),
        )
        return {"adId": ad_id, "imageKey": image_key}

    except Exception as e:
        traceback.print_exc()
        _set_status(ad_id, "error", error=f"{type(e).__name__}: {e}")
        raise
