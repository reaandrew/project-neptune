"""Lambda entrypoint for project-neptune-ads-worker.

Invoked asynchronously by ads-create. Event shape:
    {
      "adId":        "<uuid>",
      "brandJobId":  "<existing brand-jobs id>",
      "headline":    "...",     # optional
      "body":        "...",     # optional
      "cta":         "...",     # optional
      "sampleAdUrl": "..."      # optional style-reference URL
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
import sys
import time
import traceback
import urllib.request

import boto3
import yaml

ARTIFACTS_BUCKET = os.environ["ARTIFACTS_BUCKET"]
ADS_JOBS_TABLE = os.environ["ADS_JOBS_TABLE"]
OPENAI_API_KEY_PARAM = os.environ.get(
    "OPENAI_API_KEY_PARAM", "/project-neptune/openai-api-key"
)
TEXT_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o")
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
You will receive: (a) a JSON brand summary, (b) the brand-guidelines
PDF as an attached file, (c) optionally a sample-ad image as a style
cue, (d) optionally user-supplied headline/body/CTA. Any of (c)/(d)
may be empty.

Reply with EXACTLY this JSON object — no markdown, no commentary:

  {
    "headline":     "<a strong short headline, max 6 words>",
    "body":         "<1-2 sentence supporting copy>",
    "cta":          "<2-4 word call to action>",
    "image_prompt": "<a single detailed prompt for gpt-image-1>"
  }

Rules:
- If the user supplied any of headline/body/cta, copy them VERBATIM
  into the JSON (don't paraphrase). Fill the rest from the brand
  context — tone, mission, services, audience.
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
    images = (brand.get("images") or {}).get("images") or []

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
) -> dict:
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

    user_content = [
        {
            "type": "text",
            "text": (
                "Brand summary JSON (extracted from the attached "
                f"guidelines PDF):\n{json.dumps(brand_summary, indent=2)}\n\n"
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
# Step 2 — gpt-image-1 renders, with logo as reference if available
# ─────────────────────────────────────────────────────────────────────
def _render_image(prompt: str, logo_bytes: bytes | None) -> bytes:
    client = _openai()
    if logo_bytes:
        # Pass the official logo PNG as a reference image. With
        # gpt-image-1, images.edit treats the input image as a visual
        # reference the renderer should reproduce.
        resp = client.images.edit(
            model=IMAGE_MODEL,
            image=("logo.png", logo_bytes, "image/png"),
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

    started_at = str(int(time.time()))
    _set_status(ad_id, "running", started_at=started_at)

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
            summary, pdf_bytes, headline, body, cta, sample_ad_url,
        )
        print(
            f"[ad {ad_id}] copy: headline={drafted['headline']!r} "
            f"cta={drafted['cta']!r}",
            file=sys.stderr,
        )

        # ── 3. Render ──────────────────────────────────────────────
        png_bytes = _render_image(drafted["image_prompt"], logo_bytes)
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
