# -----------------------------------------------------------------------------
# Brand-guidelines worker
# -----------------------------------------------------------------------------
# Async pipeline that crawls a site, runs Bedrock vision passes, and
# renders a PDF brand-guidelines book. Triggered by brand-jobs-create
# (POST /brand-jobs), polled via brand-jobs-get (GET /brand-jobs/{id}).
#
# Components:
#   - DynamoDB table for job state
#   - S3 bucket for rendered PDFs (7-day lifecycle)
#   - ECR repo + container-image lambda (Playwright + Chromium + Python)
#   - IAM for bedrock InvokeModel, ddb writes, s3 PutObject

variable "brand_worker_image_uri" {
  type        = string
  description = "ECR image URI for the brand-worker lambda (set by CI). When empty, the lambda resource is skipped until CI provides one."
  default     = ""
}

# -----------------------------------------------------------------------------
# DynamoDB
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "brand_jobs" {
  name         = "project-neptune-brand-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Project = "project-neptune"
  }
}

# -----------------------------------------------------------------------------
# S3 — rendered PDFs
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "artifacts" {
  bucket = "project-neptune-artifacts-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-brand-jobs"
    status = "Enabled"
    filter {
      prefix = "brand-jobs/"
    }
    expiration {
      days = 7
    }
  }
}

# -----------------------------------------------------------------------------
# ECR — brand-worker image
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "brand_worker" {
  name                 = "project-neptune-brand-worker"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_ecr_lifecycle_policy" "brand_worker" {
  repository = aws_ecr_repository.brand_worker.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# -----------------------------------------------------------------------------
# IAM
# -----------------------------------------------------------------------------
# Worker role: bedrock + s3:PutObject + ddb writes
resource "aws_iam_role" "brand_worker" {
  name = "project-neptune-brand-worker"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_iam_role_policy" "brand_worker_logs" {
  name = "logs"
  role = aws_iam_role.brand_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/project-neptune-*:*"
    }]
  })
}

resource "aws_iam_role_policy" "brand_worker_bedrock" {
  name = "bedrock"
  role = aws_iam_role.brand_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
      ]
      # Allow any Claude model and any cross-region inference profile —
      # the toolkit picks a model based on AWS_REGION and may roll over
      # versions over time.
      Resource = [
        "arn:aws:bedrock:*::foundation-model/anthropic.*",
        "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*",
        "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:application-inference-profile/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "brand_worker_storage" {
  name = "storage"
  role = aws_iam_role.brand_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl",
        ]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
        ]
        Resource = aws_dynamodb_table.brand_jobs.arn
      },
    ]
  })
}

# Extend the shared lambda_exec role used by the Go lambdas: it now
# also needs ddb access on the brand-jobs table, plus lambda:InvokeFunction
# (async dispatch) and s3 read for presigning.
resource "aws_iam_role_policy" "lambda_brand_jobs" {
  name = "brand-jobs"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
        ]
        Resource = aws_dynamodb_table.brand_jobs.arn
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:project-neptune-brand-worker"
      },
      {
        # Needed for the presign signer to know the bucket exists.
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# Lambda — container image
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "brand_worker" {
  name              = "/aws/lambda/project-neptune-brand-worker"
  retention_in_days = 14

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "brand_worker" {
  count         = var.brand_worker_image_uri == "" ? 0 : 1
  function_name = "project-neptune-brand-worker"
  role          = aws_iam_role.brand_worker.arn
  package_type  = "Image"
  image_uri     = var.brand_worker_image_uri
  architectures = ["x86_64"]
  timeout       = 600
  memory_size   = 3008

  ephemeral_storage {
    size = 4096
  }

  environment {
    variables = {
      ARTIFACTS_BUCKET = aws_s3_bucket.artifacts.id
      JOBS_TABLE       = aws_dynamodb_table.brand_jobs.name
      BEDROCK_REGION   = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.brand_worker]

  tags = {
    Project = "project-neptune"
  }
}

# -----------------------------------------------------------------------------
# Lambdas — Go (create + get)
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "brand_jobs_create" {
  function_name    = "project-neptune-brand-jobs-create"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.brand_lambda["brand-jobs-create"].output_path
  source_code_hash = data.archive_file.brand_lambda["brand-jobs-create"].output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      JOBS_TABLE           = aws_dynamodb_table.brand_jobs.name
      WORKER_FUNCTION_NAME = "project-neptune-brand-worker"
    }
  }

  depends_on = [aws_cloudwatch_log_group.brand_lambda]

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "brand_jobs_get" {
  function_name    = "project-neptune-brand-jobs-get"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.brand_lambda["brand-jobs-get"].output_path
  source_code_hash = data.archive_file.brand_lambda["brand-jobs-get"].output_base64sha256
  timeout          = 5
  memory_size      = 128

  environment {
    variables = {
      JOBS_TABLE       = aws_dynamodb_table.brand_jobs.name
      ARTIFACTS_BUCKET = aws_s3_bucket.artifacts.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.brand_lambda]

  tags = {
    Project = "project-neptune"
  }
}

# Re-use the existing archive pattern: build a zip per Go lambda dir.
locals {
  brand_lambda_dirs = {
    brand-jobs-create = "../lambdas/brand-jobs-create"
    brand-jobs-get    = "../lambdas/brand-jobs-get"
  }
}

data "archive_file" "brand_lambda" {
  for_each    = local.brand_lambda_dirs
  type        = "zip"
  source_file = "${each.value}/bootstrap"
  output_path = "${each.value}/bootstrap.zip"
}

resource "aws_cloudwatch_log_group" "brand_lambda" {
  for_each          = local.brand_lambda_dirs
  name              = "/aws/lambda/project-neptune-${each.key}"
  retention_in_days = 14

  tags = {
    Project = "project-neptune"
  }
}

# -----------------------------------------------------------------------------
# API routes
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_integration" "brand_jobs_create" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.brand_jobs_create.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "brand_jobs_create" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "POST /brand-jobs"
  target             = "integrations/${aws_apigatewayv2_integration.brand_jobs_create.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "brand_jobs_create_invoke" {
  statement_id  = "AllowAPIGatewayInvokeBrandJobsCreate"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.brand_jobs_create.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/POST/brand-jobs"
}

resource "aws_apigatewayv2_integration" "brand_jobs_get" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.brand_jobs_get.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "brand_jobs_get" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "GET /brand-jobs/{id}"
  target             = "integrations/${aws_apigatewayv2_integration.brand_jobs_get.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "brand_jobs_get_invoke" {
  statement_id  = "AllowAPIGatewayInvokeBrandJobsGet"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.brand_jobs_get.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/GET/brand-jobs/*"
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "ecr_brand_worker_repo_url" {
  value = aws_ecr_repository.brand_worker.repository_url
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.id
}
