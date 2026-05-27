#!/bin/sh
# When AWS_LAMBDA_RUNTIME_API is set (production) we plug directly into
# the Lambda runtime. Otherwise we wrap with the local emulator so the
# image can be run + curl'd locally for testing.
set -e
if [ -n "${AWS_LAMBDA_RUNTIME_API}" ]; then
  exec python -m awslambdaric "$@"
else
  exec /usr/local/bin/aws-lambda-rie python -m awslambdaric "$@"
fi
