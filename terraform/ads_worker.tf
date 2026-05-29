# -----------------------------------------------------------------------------
# Ads-generation pipeline
# -----------------------------------------------------------------------------
# Async job-pattern mirror of brand_worker.tf. Reads brand context from
# the artifacts bucket, calls OpenAI (gpt-4o + gpt-image-1), writes a
# rendered ad PNG back to the same bucket.

variable "ads_worker_image_uri" {
  type        = string
  description = "ECR image URI for the ads-worker lambda (set by CI)."
  default     = ""
}

# -----------------------------------------------------------------------------
# DynamoDB
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "ads_jobs" {
  name         = "project-neptune-ads-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ad_id"

  attribute {
    name = "ad_id"
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
# ECR
# -----------------------------------------------------------------------------
data "aws_ecr_repository" "ads_worker" {
  name = "project-neptune-ads-worker"
}

resource "aws_ecr_lifecycle_policy" "ads_worker" {
  repository = data.aws_ecr_repository.ads_worker.name

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
# IAM — ads-worker role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "ads_worker" {
  name = "project-neptune-ads-worker"

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

resource "aws_iam_role_policy" "ads_worker_logs" {
  name = "logs"
  role = aws_iam_role.ads_worker.id

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

resource "aws_iam_role_policy" "ads_worker_storage" {
  name = "storage"
  role = aws_iam_role.ads_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.artifacts.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
        ]
        Resource = aws_dynamodb_table.ads_jobs.arn
      },
    ]
  })
}

resource "aws_iam_role_policy" "ads_worker_ssm" {
  name = "ssm-openai-key"
  role = aws_iam_role.ads_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/project-neptune/openai-api-key"
    }]
  })
}

# Extend the shared Go-lambda role with ads-table access + invoke perm.
resource "aws_iam_role_policy" "lambda_ads_jobs" {
  name = "ads-jobs"
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
        Resource = aws_dynamodb_table.ads_jobs.arn
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:project-neptune-ads-worker"
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# Lambda — container image ads-worker
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "ads_worker" {
  name              = "/aws/lambda/project-neptune-ads-worker"
  retention_in_days = 14

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "ads_worker" {
  count         = var.ads_worker_image_uri == "" ? 0 : 1
  function_name = "project-neptune-ads-worker"
  role          = aws_iam_role.ads_worker.arn
  package_type  = "Image"
  image_uri     = var.ads_worker_image_uri
  architectures = ["x86_64"]
  timeout       = 300
  memory_size   = 1024

  environment {
    variables = {
      ARTIFACTS_BUCKET     = aws_s3_bucket.artifacts.id
      ADS_JOBS_TABLE       = aws_dynamodb_table.ads_jobs.name
      OPENAI_API_KEY_PARAM = "/project-neptune/openai-api-key"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ads_worker]

  tags = {
    Project = "project-neptune"
  }
}

# -----------------------------------------------------------------------------
# Go lambdas — ads-create + ads-get
# -----------------------------------------------------------------------------
locals {
  ads_lambda_dirs = {
    ads-create = "../lambdas/ads-create"
    ads-get    = "../lambdas/ads-get"
    ads-list   = "../lambdas/ads-list"
  }
}

data "archive_file" "ads_lambda" {
  for_each    = local.ads_lambda_dirs
  type        = "zip"
  source_file = "${each.value}/bootstrap"
  output_path = "${each.value}/bootstrap.zip"
}

resource "aws_cloudwatch_log_group" "ads_lambda" {
  for_each          = local.ads_lambda_dirs
  name              = "/aws/lambda/project-neptune-${each.key}"
  retention_in_days = 14

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "ads_create" {
  function_name    = "project-neptune-ads-create"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.ads_lambda["ads-create"].output_path
  source_code_hash = data.archive_file.ads_lambda["ads-create"].output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      ADS_JOBS_TABLE       = aws_dynamodb_table.ads_jobs.name
      BRAND_JOBS_TABLE     = aws_dynamodb_table.brand_jobs.name
      WORKER_FUNCTION_NAME = "project-neptune-ads-worker"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ads_lambda]

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "ads_list" {
  function_name    = "project-neptune-ads-list"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.ads_lambda["ads-list"].output_path
  source_code_hash = data.archive_file.ads_lambda["ads-list"].output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      ADS_JOBS_TABLE = aws_dynamodb_table.ads_jobs.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.ads_lambda]

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_apigatewayv2_integration" "ads_list" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ads_list.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "ads_list" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "GET /ads"
  target             = "integrations/${aws_apigatewayv2_integration.ads_list.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "ads_list_invoke" {
  statement_id  = "AllowAPIGatewayInvokeAdsList"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ads_list.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/GET/ads"
}

resource "aws_lambda_function" "ads_get" {
  function_name    = "project-neptune-ads-get"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.ads_lambda["ads-get"].output_path
  source_code_hash = data.archive_file.ads_lambda["ads-get"].output_base64sha256
  timeout          = 5
  memory_size      = 128

  environment {
    variables = {
      ADS_JOBS_TABLE   = aws_dynamodb_table.ads_jobs.name
      ARTIFACTS_BUCKET = aws_s3_bucket.artifacts.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.ads_lambda]

  tags = {
    Project = "project-neptune"
  }
}

# -----------------------------------------------------------------------------
# API routes
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_integration" "ads_create" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ads_create.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "ads_create" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "POST /ads"
  target             = "integrations/${aws_apigatewayv2_integration.ads_create.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "ads_create_invoke" {
  statement_id  = "AllowAPIGatewayInvokeAdsCreate"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ads_create.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/POST/ads"
}

resource "aws_apigatewayv2_integration" "ads_get" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ads_get.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "ads_get" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "GET /ads/{id}"
  target             = "integrations/${aws_apigatewayv2_integration.ads_get.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "ads_get_invoke" {
  statement_id  = "AllowAPIGatewayInvokeAdsGet"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ads_get.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/GET/ads/*"
}

output "ecr_ads_worker_repo_url" {
  value = data.aws_ecr_repository.ads_worker.repository_url
}
