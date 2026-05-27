# -----------------------------------------------------------------------------
# Lambda execution role
# -----------------------------------------------------------------------------
# One role shared by both lambdas. The authorizer reads the ara JWT
# signing key from SSM; the message lambda needs no secrets but inherits
# the same role for simplicity.

resource "aws_iam_role" "lambda_exec" {
  name = "project-neptune-lambda-exec"

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

resource "aws_iam_role_policy" "lambda_logs" {
  name = "logs"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/project-neptune-*:*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_ssm" {
  name = "ssm-read"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssm:GetParameter",
        "ssm:GetParameters",
      ]
      Resource = [
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/ara/jwt-signing-key",
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/project-neptune/*",
      ]
    }]
  })
}

# -----------------------------------------------------------------------------
# Lambdas
# -----------------------------------------------------------------------------
locals {
  lambda_dirs = {
    api-authorizer = "../lambdas/api-authorizer"
    message-get    = "../lambdas/message-get"
  }
}

data "archive_file" "lambda" {
  for_each    = local.lambda_dirs
  type        = "zip"
  source_file = "${each.value}/bootstrap"
  output_path = "${each.value}/bootstrap.zip"
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.lambda_dirs
  name              = "/aws/lambda/project-neptune-${each.key}"
  retention_in_days = 14

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "api_authorizer" {
  function_name    = "project-neptune-api-authorizer"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.lambda["api-authorizer"].output_path
  source_code_hash = data.archive_file.lambda["api-authorizer"].output_base64sha256
  timeout          = 5
  memory_size      = 128

  environment {
    variables = {
      JWT_SIGNING_KEY_PARAM = "/ara/jwt-signing-key"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_lambda_function" "message_get" {
  function_name    = "project-neptune-message-get"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "provided.al2023"
  handler          = "bootstrap"
  architectures    = ["x86_64"]
  filename         = data.archive_file.lambda["message-get"].output_path
  source_code_hash = data.archive_file.lambda["message-get"].output_base64sha256
  timeout          = 5
  memory_size      = 128

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = {
    Project = "project-neptune"
  }
}
