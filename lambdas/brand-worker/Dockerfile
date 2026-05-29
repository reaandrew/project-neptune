# Lambda container image for the brand-guidelines worker.
#
# Built on the official Playwright Python image (Ubuntu 22 + Chromium +
# all the X libs Chromium needs) and converted into a Lambda image by
# layering on top:
#   - awslambdaric (Lambda Runtime Interface Client)
#   - The Lambda Runtime Interface Emulator (RIE) for local testing
#
# Chromium in Lambda needs --no-sandbox; probe_brand.py already passes
# that via Playwright launch args.

FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    LAMBDA_TASK_ROOT=/var/task

WORKDIR ${LAMBDA_TASK_ROOT}

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt \
 && playwright install chromium

COPY *.py ./

# Lambda Runtime Interface Emulator — only invoked locally.
ADD https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie /usr/local/bin/aws-lambda-rie
RUN chmod +x /usr/local/bin/aws-lambda-rie

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["handler.handler"]
