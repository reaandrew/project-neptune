# -----------------------------------------------------------------------------
# api.projectneptune.andrewreaassociates.com
# -----------------------------------------------------------------------------
# HTTP API (APIGW v2). Routes are guarded by a Lambda authorizer that
# validates the JWT issued by ara. The browser never calls this host
# directly — bff.projectneptune.* fronts it and rewrites the cookie into
# an Authorization header.

resource "aws_apigatewayv2_api" "api" {
  name          = "project-neptune-api"
  protocol_type = "HTTP"

  # The BFF terminates the browser CORS contract; the API only gets
  # already-authorized calls from CloudFront. We still set basic CORS
  # so that direct test calls (curl + Authorization) work.
  cors_configuration {
    allow_origins     = ["https://projectneptune.andrewreaassociates.com"]
    allow_methods     = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_headers     = ["Content-Type", "Authorization"]
    allow_credentials = true
  }

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/project-neptune-api"
  retention_in_days = 14

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  tags = {
    Project = "project-neptune"
  }
}

# -----------------------------------------------------------------------------
# Authorizer (Lambda, simple response)
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id                            = aws_apigatewayv2_api.api.id
  authorizer_type                   = "REQUEST"
  identity_sources                  = ["$request.header.Authorization"]
  name                              = "project-neptune-jwt"
  authorizer_uri                    = aws_lambda_function.api_authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  # Don't cache; the BFF strips cookies into headers per request so the
  # authorizer must evaluate every call. With a small auth lambda this
  # is cheap.
  authorizer_result_ttl_in_seconds = 0
}

resource "aws_lambda_permission" "authorizer_invoke" {
  statement_id  = "AllowAPIGatewayInvokeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.jwt.id}"
}

# -----------------------------------------------------------------------------
# Routes + integrations
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_integration" "message_get" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.message_get.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "message_get" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "GET /message"
  target             = "integrations/${aws_apigatewayv2_integration.message_get.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "message_get_invoke" {
  statement_id  = "AllowAPIGatewayInvokeMessage"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.message_get.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/GET/message"
}

# -----------------------------------------------------------------------------
# Custom domain api.projectneptune.andrewreaassociates.com
# -----------------------------------------------------------------------------
resource "aws_acm_certificate" "api" {
  domain_name       = "api.projectneptune.andrewreaassociates.com"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_route53_record" "api_cert_validation" {
  provider = aws.dns

  for_each = {
    for dvo in aws_acm_certificate.api.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = var.hosted_zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in aws_route53_record.api_cert_validation : r.fqdn]
}

resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = "api.projectneptune.andrewreaassociates.com"

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.api.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = aws_apigatewayv2_stage.api.id
}

resource "aws_route53_record" "api" {
  provider = aws.dns
  zone_id  = var.hosted_zone_id
  name     = "api.projectneptune.andrewreaassociates.com"
  type     = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

output "api_endpoint" {
  value = "https://api.projectneptune.andrewreaassociates.com"
}
