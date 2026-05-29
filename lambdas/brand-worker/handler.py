"""Lambda entrypoint for project-neptune-brand-worker.

Invoked asynchronously by brand-jobs-create. Event shape:
    {"jobId": "<uuid>", "url": "https://example.com"}

Runs the brand-guidelines pipeline, uploads the PDF to the artifacts
bucket under `brand-jobs/<jobId>.pdf`, and updates the brand-jobs DDB
row with status = done | error.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

import boto3
import yaml

ARTIFACTS_BUCKET = os.environ["ARTIFACTS_BUCKET"]
JOBS_TABLE = os.environ["JOBS_TABLE"]
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "eu-west-2"))

# Honour the toolkit's region-resolution by also exporting these.
os.environ.setdefault("AWS_REGION", BEDROCK_REGION)
os.environ.setdefault("AWS_DEFAULT_REGION", BEDROCK_REGION)

_ddb = boto3.client("dynamodb")
_s3 = boto3.client("s3")


def _set_status(job_id: str, status: str, **extra: str) -> None:
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
        TableName=JOBS_TABLE,
        Key={"job_id": {"S": job_id}},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def handler(event, _context):
    job_id = event["jobId"]
    url = event["url"]

    workdir = Path(f"/tmp/{job_id}")
    workdir.mkdir(parents=True, exist_ok=True)
    pdf_path = workdir / "brand_guidelines.pdf"
    yaml_path = workdir / "brand.yaml"
    screenshot_dir = workdir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    started_at = str(int(time.time()))
    _set_status(job_id, "running", started_at=started_at)

    # Drive the existing CLI by setting sys.argv. The toolkit was
    # written as a script first; calling main() is the supported entry.
    # --save-yaml persists the intermediate brand dict so we can also
    # serve it as a structured artifact alongside the PDF.
    sys.argv = [
        "build_brand_guidelines.py",
        url,
        "-o", str(pdf_path),
        "--save-yaml", str(yaml_path),
        "--screenshot-dir", str(screenshot_dir),
        "--bedrock-region", BEDROCK_REGION,
    ]
    # Add toolkit dir (this file's directory) to sys.path so the
    # modules import cleanly when running inside the Lambda container.
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        import build_brand_guidelines  # noqa: WPS433 — lazy import is intentional
        build_brand_guidelines.main()
    except SystemExit as e:
        if e.code not in (None, 0):
            _set_status(job_id, "error", error=f"toolkit exit {e.code}")
            raise
    except Exception as e:
        traceback.print_exc()
        _set_status(job_id, "error", error=f"{type(e).__name__}: {e}")
        raise

    if not pdf_path.exists():
        _set_status(job_id, "error", error="pdf not produced")
        raise RuntimeError("pdf not produced")

    pdf_key = f"brand-jobs/{job_id}.pdf"
    _s3.put_object(
        Bucket=ARTIFACTS_BUCKET,
        Key=pdf_key,
        Body=pdf_path.read_bytes(),
        ContentType="application/pdf",
    )

    yaml_key = None
    json_key = None
    brand_dict: dict = {}
    if yaml_path.exists():
        yaml_bytes = yaml_path.read_bytes()
        yaml_key = f"brand-jobs/{job_id}.yaml"
        _s3.put_object(
            Bucket=ARTIFACTS_BUCKET,
            Key=yaml_key,
            Body=yaml_bytes,
            ContentType="application/yaml",
        )
        try:
            brand_dict = yaml.safe_load(yaml_bytes.decode("utf-8")) or {}
            json_bytes = json.dumps(brand_dict, indent=2, ensure_ascii=False).encode("utf-8")
            json_key = f"brand-jobs/{job_id}.json"
            _s3.put_object(
                Bucket=ARTIFACTS_BUCKET,
                Key=json_key,
                Body=json_bytes,
                ContentType="application/json",
            )
        except Exception as e:
            print(f"  ! failed to convert yaml -> json ({e})", file=sys.stderr)

    # Upload the home-fold homepage screenshot — used as a card hero on
    # the brands list + the brand-detail page. Silently fall through if
    # Playwright didn't capture one (probe failed).
    screenshot_key = None
    home_fold = screenshot_dir / "01_home_fold.png"
    if home_fold.exists():
        try:
            screenshot_key = f"brand-jobs/{job_id}.png"
            _s3.put_object(
                Bucket=ARTIFACTS_BUCKET,
                Key=screenshot_key,
                Body=home_fold.read_bytes(),
                ContentType="image/png",
            )
        except Exception as e:
            print(f"  ! failed to upload screenshot ({e})", file=sys.stderr)
            screenshot_key = None

    # Pluck the identity bits the list endpoint will surface as a
    # thumbnail + chip. None of these are required for the brand book
    # to be valid — gracefully fall through if missing.
    style = (brand_dict.get("style") or {}) if isinstance(brand_dict, dict) else {}
    brand_id = style.get("brand") or {}
    content = (brand_dict.get("content") or {}) if isinstance(brand_dict, dict) else {}
    essence = content.get("essence") or {}
    images = (brand_dict.get("images") or {}) if isinstance(brand_dict, dict) else {}
    image_list = images.get("images") or []
    primary_logo = next(
        (im.get("url") for im in image_list if im.get("role") == "brand_primary"),
        None,
    ) or next(
        (im.get("url") for im in image_list if im.get("role") == "logo"),
        None,
    )
    brand_name = (
        essence.get("brand_name")
        or brand_id.get("brand_name")
        or brand_dict.get("domain")
    )

    completed_at = str(int(time.time()))
    extras = {"pdf_key": pdf_key, "completed_at": completed_at}
    if yaml_key:
        extras["yaml_key"] = yaml_key
    if json_key:
        extras["json_key"] = json_key
    if screenshot_key:
        extras["screenshot_key"] = screenshot_key
    if primary_logo:
        extras["logo_url"] = primary_logo
    if brand_id.get("primary_color"):
        extras["primary_color"] = brand_id["primary_color"]
    if brand_name:
        extras["brand_name"] = brand_name
    _set_status(job_id, "done", **extras)

    return {"jobId": job_id, "pdfKey": pdf_key, "yamlKey": yaml_key, "jsonKey": json_key}
