# project-neptune

Blank-canvas SaaS skeleton behind a shared `.andrewreaassociates.com`
passkey session. Renders a welcome page that proves the
`client → BFF → API` round trip works.

```
        ┌──────────────────────────────────────────────────────────────┐
        │  Browser (https://projectneptune.andrewreaassociates.com)    │
        │   - Vite + React + Tailwind                                  │
        │   - All API calls via credentials:'include'                  │
        └─────────────────────────┬────────────────────────────────────┘
                                  │ cookie: auth_token=<jwt>
                                  ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  bff.projectneptune.andrewreaassociates.com (CloudFront)     │
        │   CF Function viewer-request:                                │
        │     cookie auth_token  →  Authorization: Bearer <jwt>        │
        └─────────────────────────┬────────────────────────────────────┘
                                  ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  api.projectneptune.andrewreaassociates.com (APIGW v2)       │
        │   Lambda authorizer verifies HS256 JWT against the shared    │
        │   /ara/jwt-signing-key SSM parameter.                        │
        │   Routes:                                                    │
        │     GET /message  →  message-get lambda                      │
        └──────────────────────────────────────────────────────────────┘

  Login flow: client app sends user to
    https://andrewreaassociates.com/admin.html?returnTo=<current page>
  ara completes passkey login and sets
    auth_token=<jwt>; Domain=.andrewreaassociates.com; HttpOnly; Secure
  then redirects back. Browser now sends the cookie to bff.* on
  subsequent calls. Cookie is never exposed to JS in the browser.
```

## Layout

```
.
├── aws-setup/             OIDC + IAM role for CI (personal_iphone).
├── aws-setup-dns/         Cross-account dns-writer role (personal_legacy).
├── terraform/
│   ├── main.tf            Site bucket + CloudFront + providers.
│   ├── lambda.tf          Lambda exec role + functions.
│   ├── api.tf             APIGW v2 + custom domain api.*
│   ├── bff.tf             CloudFront BFF + CF Function + custom domain bff.*
│   ├── site-auth-gate.tf  Edge JWT cookie gate for the static site.
│   └── cloudfront-functions/
│       ├── cookie-to-auth.js
│       └── site-auth-gate.js.tftpl
├── lambdas/
│   ├── go.mod
│   ├── internal/auth      JWT verification (HS256 vs ara key).
│   ├── api-authorizer/    API Gateway Lambda authorizer.
│   └── message-get/       GET /message  →  { "message": "..." }
├── frontend/              Vite + React + TS + Tailwind. Single welcome page.
└── .github/workflows/deploy.yml
```

## Hosts

| Host                                                          | What                                          |
| ------------------------------------------------------------- | --------------------------------------------- |
| https://projectneptune.andrewreaassociates.com                | React app (static, CloudFront)                |
| https://bff.projectneptune.andrewreaassociates.com            | BFF — only `bff` calls hit it                 |
| https://api.projectneptune.andrewreaassociates.com            | API Gateway — never called from browser       |
| https://andrewreaassociates.com/admin.html                    | ara passkey login                             |
| https://auth.andrewreaassociates.com                          | ara API (where the cookie is set)             |

## Bootstrap (one-off)

```bash
# personal_iphone (276447169330): state bucket + OIDC role + lambda/apigw/ssm policies
aws-vault exec personal_iphone -- aws s3api create-bucket \
  --bucket project-neptune-tfstate-276447169330 \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2
cd aws-setup
aws-vault exec personal_iphone -- terraform init
aws-vault exec personal_iphone -- terraform apply

# personal_legacy (776648872426): cross-account DNS writer role for andrewreaassociates.com
aws-vault exec personal_legacy -- aws s3api create-bucket \
  --bucket project-neptune-tfstate-776648872426 \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2
cd ../aws-setup-dns
aws-vault exec personal_legacy -- terraform init
aws-vault exec personal_legacy -- terraform apply
```

Then in the `reaandrew/project-neptune` repo: set `AWS_ROLE_ARN` GitHub secret to the
`github_actions_role_arn` output of `aws-setup`. Push to `main` to deploy.

## Adding a feature

The skeleton is intentionally empty. To add a new endpoint:

1. Add a Go package under `lambdas/<name>/` with an APIGW v2 HTTP handler.
2. Wire it up in `terraform/lambda.tf` (add to `lambda_dirs` + an `aws_lambda_function`)
   and `terraform/api.tf` (integration + route + `lambda:InvokeFunction` permission).
3. Add the matrix entry in `.github/workflows/deploy.yml` (build-lambdas matrix
   and the "Place lambda binaries" loop).
4. Call it from `frontend/src/lib/api.ts` via the BFF; render in a page under
   `frontend/src/pages/`.
