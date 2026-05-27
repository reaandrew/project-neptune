# Cross-account DNS bootstrap. Applied manually with:
#   aws-vault exec personal_legacy -- terraform apply
#
# Creates an IAM role in personal_legacy (776648872426) that the
# github-actions-project-neptune role in personal_iphone (276447169330)
# can assume to manage records in the andrewreaassociates.com zone.

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "project-neptune-tfstate-776648872426"
    key    = "aws-setup-dns/terraform.tfstate"
    region = "eu-west-2"
  }
}

provider "aws" {
  region = "eu-west-2"
}

variable "trusted_role_arn" {
  type        = string
  description = "ARN of the role in the other account that may assume this role."
  default     = "arn:aws:iam::276447169330:role/github-actions-project-neptune"
}

variable "hosted_zone_id" {
  type    = string
  default = "Z35TVV0OK1J0JO"
}

variable "subdomain_fqdn" {
  type    = string
  default = "projectneptune.andrewreaassociates.com"
}

resource "aws_iam_role" "dns_writer" {
  name = "project-neptune-dns-writer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.trusted_role_arn }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project   = "project-neptune"
    ManagedBy = "Terraform"
  }
}

resource "aws_iam_role_policy" "route53" {
  name = "route53-projectneptune"
  role = aws_iam_role.dns_writer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadZone"
        Effect = "Allow"
        Action = [
          "route53:ListHostedZones",
          "route53:GetHostedZone",
          "route53:ListResourceRecordSets",
          "route53:GetChange",
          "route53:ListTagsForResource",
        ]
        Resource = "*"
      },
      {
        Sid      = "WriteSubdomainRecords"
        Effect   = "Allow"
        Action   = ["route53:ChangeResourceRecordSets"]
        Resource = "arn:aws:route53:::hostedzone/${var.hosted_zone_id}"
        # Limit writes to projectneptune.* records only (ACM validation
        # CNAME has _<hash>.projectneptune.<zone> shape, so the wildcard
        # below covers both the alias and the cert validation record).
        Condition = {
          "ForAllValues:StringLike" = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = [
              var.subdomain_fqdn,
              "*.${var.subdomain_fqdn}",
            ]
          }
        }
      }
    ]
  })
}

output "dns_writer_role_arn" {
  value = aws_iam_role.dns_writer.arn
}
