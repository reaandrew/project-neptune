# Small Python container for the ads-worker.
# No Playwright/Chromium — this lambda only talks to OpenAI + S3 + DDB.

FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY *.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
