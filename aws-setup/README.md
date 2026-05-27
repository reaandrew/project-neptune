# aws-setup

Bootstrap IAM resources that let GitHub Actions deploy into this AWS account via OIDC. Applied once by hand from a workstation that already has admin credentials; thereafter the workflow uses the role this stack creates.

## What it creates

- `aws_iam_openid_connect_provider.github` — trusts `token.actions.githubusercontent.com`.
- `aws_iam_role.github-actions-project-neptune` — assumable by any workflow run on `repo:reaandrew/project-neptune:*`.
- Inline policies on the role: read/write the terraform state bucket, full lifecycle on `project-neptune-site-<acct>`, plus lambda/apigw/cloudfront/acm/ssm-read/logs scoped to `project-neptune-*`.

## One-time bootstrap

```bash
# In an AWS_* exported shell with admin creds (account 276447169330):
aws s3api create-bucket \
  --bucket project-neptune-tfstate-276447169330 \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2
aws s3api put-bucket-versioning \
  --bucket project-neptune-tfstate-276447169330 \
  --versioning-configuration Status=Enabled

cd aws-setup
terraform init
terraform apply
```

Copy `github_actions_role_arn` from the output and set it as the `AWS_ROLE_ARN` GitHub Actions secret on the repo.

If the account already has the GitHub OIDC provider, import it first:

```bash
terraform import aws_iam_openid_connect_provider.github \
  arn:aws:iam::276447169330:oidc-provider/token.actions.githubusercontent.com
```
