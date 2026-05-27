"""Lambda entrypoint for project-neptune-brand-worker.

Invoked asynchronously by brand-jobs-create. Event shape:
    {"jobId": "<uuid>", "url": "https://example.com"}

Runs the brand-guidelines pipeline, uploads the PDF to the artifacts
bucket under `brand-jobs/<jobId>.pdf`, and updates the brand-jobs DDB
row with status = done | error.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

import boto3

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
    screenshot_dir = workdir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    started_at = str(int(time.time()))
    _set_status(job_id, "running", started_at=started_at)

    # Drive the existing CLI by setting sys.argv. The toolkit was
    # written as a script first; calling main() is the supported entry.
    sys.argv = [
        "build_brand_guidelines.py",
        url,
        "-o", str(pdf_path),
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

    s3_key = f"brand-jobs/{job_id}.pdf"
    _s3.put_object(
        Bucket=ARTIFACTS_BUCKET,
        Key=s3_key,
        Body=pdf_path.read_bytes(),
        ContentType="application/pdf",
    )

    completed_at = str(int(time.time()))
    _set_status(
        job_id, "done",
        pdf_key=s3_key,
        completed_at=completed_at,
    )

    return {"jobId": job_id, "pdfKey": s3_key}
