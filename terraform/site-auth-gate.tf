# Site-edge authentication gate.
#
# A CloudFront Function attached to the projectneptune.* distribution's
# viewer-request stage. It cryptographically validates the auth_token
# JWT cookie against the shared ara HMAC secret. Requests without a
# valid token are redirected (302) to ara's passkey login page before
# any HTML leaves CloudFront.
#
# The signing secret is read from SSM at terraform-apply time and
# embedded in the function code via templatefile. Rotation = terraform
# apply.

data "aws_ssm_parameter" "ara_jwt_signing_key" {
  name            = "/ara/jwt-signing-key"
  with_decryption = true
}

resource "aws_cloudfront_function" "site_auth_gate" {
  name    = "project-neptune-site-auth-gate"
  runtime = "cloudfront-js-2.0"
  publish = true
  comment = "JWT cookie gate for the projectneptune static site"

  code = templatefile("${path.module}/cloudfront-functions/site-auth-gate.js.tftpl", {
    signing_key = data.aws_ssm_parameter.ara_jwt_signing_key.value
  })
}
