# -----------------------------------------------------------------------------
# bff.projectneptune.andrewreaassociates.com
# -----------------------------------------------------------------------------
# Pure-CloudFront BFF (no Lambda). A CloudFront Function pulls the
# `auth_token` cookie from incoming requests and rewrites it into an
# Authorization header before forwarding to the API origin.

resource "aws_cloudfront_function" "cookie_to_auth" {
  name    = "project-neptune-cookie-to-auth"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = file("${path.module}/cloudfront-functions/cookie-to-auth.js")
  comment = "Pulls auth_token cookie into an Authorization: Bearer header"
}

# Cert for bff.* — CloudFront aliases need certs in us-east-1.
resource "aws_acm_certificate" "bff" {
  provider          = aws.virginia
  domain_name       = "bff.projectneptune.andrewreaassociates.com"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_route53_record" "bff_cert_validation" {
  provider = aws.dns

  for_each = {
    for dvo in aws_acm_certificate.bff.domain_validation_options : dvo.domain_name => {
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

resource "aws_acm_certificate_validation" "bff" {
  provider                = aws.virginia
  certificate_arn         = aws_acm_certificate.bff.arn
  validation_record_fqdns = [for r in aws_route53_record.bff_cert_validation : r.fqdn]
}

# AWS-managed "AllViewerExceptHostHeader" origin request policy — sends
# all viewer headers (Authorization, etc.) to the origin except Host.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# AWS-managed "CachingDisabled" — API responses must not be cached.
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

resource "aws_cloudfront_distribution" "bff" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "project-neptune BFF (cookie → Authorization header)"
  price_class     = "PriceClass_100"

  aliases = ["bff.projectneptune.andrewreaassociates.com"]

  origin {
    domain_name = aws_apigatewayv2_domain_name.api.domain_name
    origin_id   = "api-projectneptune"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "api-projectneptune"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.cookie_to_auth.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.bff.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = {
    Project = "project-neptune"
  }
}

resource "aws_route53_record" "bff_a" {
  provider = aws.dns
  zone_id  = var.hosted_zone_id
  name     = "bff.projectneptune.andrewreaassociates.com"
  type     = "A"

  alias {
    name                   = aws_cloudfront_distribution.bff.domain_name
    zone_id                = aws_cloudfront_distribution.bff.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "bff_aaaa" {
  provider = aws.dns
  zone_id  = var.hosted_zone_id
  name     = "bff.projectneptune.andrewreaassociates.com"
  type     = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.bff.domain_name
    zone_id                = aws_cloudfront_distribution.bff.hosted_zone_id
    evaluate_target_health = false
  }
}

output "bff_url" {
  value = "https://bff.projectneptune.andrewreaassociates.com"
}
