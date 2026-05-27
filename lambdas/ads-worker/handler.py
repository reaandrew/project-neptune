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
  1. Load the brand.yaml + the brand-guidelines PDF from the artifacts
     bucket using brandJobId.
  2. Ask GPT-4o (text) to read the brand context + user requirements and
     return a single, detailed image prompt that respects the brand and
     the user-supplied SYSTEM_PROMPT below.
  3. Ask gpt-image-1 to render that prompt as a 1024x1024 PNG.
  4. Upload the PNG to s3://artifacts/ads/<adId>.png, mark the ad-job done.

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


# ─────────────────────────────────────────────────────────────────────
# OpenAI client
# ─────────────────────────────────────────────────────────────────────
_openai_client = None


def _openai():
    global _openai_client
    if _openai_client is None:
        out = _ssm.get_parameter(Name=OPENAI_API_KEY_PARAM, WithDecryption=True)
        from openai import OpenAI  # imported lazily so cold start without key still loads
        _openai_client = OpenAI(api_key=out["Parameter"]["Value"])
    return _openai_client


# ─────────────────────────────────────────────────────────────────────
# DynamoDB helpers
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


def _brand_summary(brand: dict) -> dict:
    """Project the brand.yaml down to the fields the image model needs.
    Sending the whole 200KB+ YAML wastes tokens and confuses the model
    with irrelevant DOM scraping artefacts."""
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

    return {
        "domain": brand.get("domain"),
        "start_url": brand.get("start_url"),
        "brand_name": essence.get("brand_name") or brand_id.get("brand_name"),
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


# ─────────────────────────────────────────────────────────────────────
# Step 1 — draft a detailed image prompt with gpt-4o
# ─────────────────────────────────────────────────────────────────────
def _draft_image_prompt(
    brand_summary: dict,
    headline: str,
    body: str,
    cta: str,
    sample_ad_url: str,
) -> str:
    user_brief = {
        "brand": brand_summary,
        "advert_requirements": {
            "headline": headline or None,
            "supporting_copy": body or None,
            "call_to_action": cta or None,
        },
    }
    if sample_ad_url:
        user_brief["style_reference_image_url"] = sample_ad_url

    # Multi-part user message: include the optional sample-ad image so
    # gpt-4o can describe its layout characteristics.
    user_content = [
        {
            "type": "text",
            "text": (
                "Below is the brand context (extracted from the brand "
                "guidelines PDF) and the user's advert requirements. "
                "Produce a single detailed image-generation prompt for "
                "a 1024x1024 Facebook advert image that follows the "
                "system instructions strictly. Reply with ONLY the "
                "prompt text — no commentary, no JSON, no preamble.\n\n"
                "BRIEF:\n"
                f"{json.dumps(user_brief, indent=2)}"
            ),
        }
    ]
    if sample_ad_url:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": sample_ad_url},
        })

    client = _openai()
    resp = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    prompt = (resp.choices[0].message.content or "").strip()
    if not prompt:
        raise RuntimeError("text model returned empty prompt")
    return prompt


# ─────────────────────────────────────────────────────────────────────
# Step 2 — render with gpt-image-1
# ─────────────────────────────────────────────────────────────────────
def _render_image(prompt: str) -> bytes:
    client = _openai()
    resp = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size=IMAGE_SIZE,
        quality=IMAGE_QUALITY,
        n=1,
    )
    b64 = resp.data[0].b64_json
    if not b64:
        # Some SDK versions return a URL instead of b64 — fetch it.
        url = resp.data[0].url
        if not url:
            raise RuntimeError("image model returned neither b64_json nor url")
        import urllib.request
        with urllib.request.urlopen(url) as r:
            return r.read()
    return base64.b64decode(b64)


# ─────────────────────────────────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────────────────────────────────
def handler(event, _context):
    ad_id = event["adId"]
    brand_job_id = event["brandJobId"]
    headline = event.get("headline", "") or ""
    body = event.get("body", "") or ""
    cta = event.get("cta", "") or ""
    sample_ad_url = event.get("sampleAdUrl", "") or ""

    started_at = str(int(time.time()))
    _set_status(ad_id, "running", started_at=started_at)

    try:
        # Load brand.yaml from S3.
        yaml_key = f"brand-jobs/{brand_job_id}.yaml"
        try:
            obj = _s3.get_object(Bucket=ARTIFACTS_BUCKET, Key=yaml_key)
        except Exception as e:
            raise RuntimeError(f"brand yaml not found at s3://{ARTIFACTS_BUCKET}/{yaml_key}: {e}")
        brand_dict = yaml.safe_load(obj["Body"].read().decode("utf-8"))
        summary = _brand_summary(brand_dict)

        # Step 1: draft an image prompt.
        prompt = _draft_image_prompt(summary, headline, body, cta, sample_ad_url)
        print(f"[ad {ad_id}] drafted prompt ({len(prompt)} chars)", file=sys.stderr)

        # Step 2: render.
        png_bytes = _render_image(prompt)
        print(f"[ad {ad_id}] rendered image ({len(png_bytes)} bytes)", file=sys.stderr)

        image_key = f"ads/{ad_id}.png"
        _s3.put_object(
            Bucket=ARTIFACTS_BUCKET,
            Key=image_key,
            Body=png_bytes,
            ContentType="image/png",
        )

        prompt_key = f"ads/{ad_id}.prompt.txt"
        _s3.put_object(
            Bucket=ARTIFACTS_BUCKET,
            Key=prompt_key,
            Body=prompt.encode("utf-8"),
            ContentType="text/plain",
        )

        _set_status(
            ad_id, "done",
            image_key=image_key,
            prompt_key=prompt_key,
            completed_at=str(int(time.time())),
        )
        return {"adId": ad_id, "imageKey": image_key}

    except Exception as e:
        traceback.print_exc()
        _set_status(ad_id, "error", error=f"{type(e).__name__}: {e}")
        raise
