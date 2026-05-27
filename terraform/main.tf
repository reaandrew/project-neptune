terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket = "project-neptune-tfstate-276447169330"
    key    = "site/terraform.tfstate"
    region = "eu-west-2"
  }
}

variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "domain_name" {
  type    = string
  default = "projectneptune.andrewreaassociates.com"
}

variable "hosted_zone_id" {
  type    = string
  default = "Z35TVV0OK1J0JO"
}

variable "dns_writer_role_arn" {
  type    = string
  default = "arn:aws:iam::776648872426:role/project-neptune-dns-writer"
}

# Default provider: site account, eu-west-2.
provider "aws" {
  region = var.aws_region
}

# CloudFront/ACM custom domain certs must live in us-east-1.
provider "aws" {
  alias  = "virginia"
  region = "us-east-1"
}

# Cross-account: assume the DNS writer role in personal_legacy to manage
# records in the andrewreaassociates.com hosted zone.
provider "aws" {
  alias  = "dns"
  region = "eu-west-2"
  assume_role {
    role_arn     = var.dns_writer_role_arn
    session_name = "project-neptune-tf"
  }
}

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "project-neptune-site-${data.aws_caller_identity.current.account_id}"
}

# ---------- S3 bucket (private; served via CloudFront OAC) ----------
resource "aws_s3_bucket" "site" {
  bucket = local.bucket_name

  tags = {
    Project   = "project-neptune"
    ManagedBy = "Terraform"
  }
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lock the bucket so only the CloudFront distribution can read it.
data "aws_iam_policy_document" "site" {
  statement {
    sid     = "AllowCloudFrontRead"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.site.arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site.json
  depends_on = [
    aws_s3_bucket_public_access_block.site,
  ]
}

# ---------- ACM certificate (us-east-1 for CloudFront) ----------
resource "aws_acm_certificate" "site" {
  provider          = aws.virginia
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Project = "project-neptune"
  }
}

# DNS validation record(s) — written into the personal_legacy zone.
resource "aws_route53_record" "cert_validation" {
  provider = aws.dns

  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
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

resource "aws_acm_certificate_validation" "site" {
  provider                = aws.virginia
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# ---------- CloudFront distribution ----------
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "project-neptune-oac"
  description                       = "OAC for project-neptune S3 origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "project-neptune static site"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  aliases = [var.domain_name]

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3-${aws_s3_bucket.site.id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-${aws_s3_bucket.site.id}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS-managed "CachingOptimized" cache policy.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    # Edge auth gate: redirect to ara passkey login if the auth_token
    # cookie is missing/invalid/expired. Nothing is served from S3
    # without a verified JWT.
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.site_auth_gate.arn
    }
  }

  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 60
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 60
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = {
    Project = "project-neptune"
  }
}

# ---------- Route53 alias to CloudFront ----------
resource "aws_route53_record" "site_a" {
  provider = aws.dns
  zone_id  = var.hosted_zone_id
  name     = var.domain_name
  type     = "A"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "site_aaaa" {
  provider = aws.dns
  zone_id  = var.hosted_zone_id
  name     = var.domain_name
  type     = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

# ---------- Outputs ----------
output "bucket_name" {
  value = aws_s3_bucket.site.id
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.site.domain_name
}

output "site_url" {
  value = "https://${var.domain_name}"
}
