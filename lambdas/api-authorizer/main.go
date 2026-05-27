// project-neptune API Gateway Lambda authorizer.
//
// Validates the bearer JWT in the incoming Authorization header against
// the shared ara HS256 secret stored at /ara/jwt-signing-key. The BFF
// CloudFront Function rewrites the request: it pulls `auth_token` from
// the user's cookie and writes it as an Authorization header before the
// request reaches API Gateway, so the cookie itself never appears here.
package main

import (
	"context"
	"log"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ssm"

	"github.com/reaandrew/project-neptune/lambdas/internal/auth"
)

func handler(ctx context.Context, req events.APIGatewayV2CustomAuthorizerV2Request) (events.APIGatewayV2CustomAuthorizerSimpleResponse, error) {
	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return events.APIGatewayV2CustomAuthorizerSimpleResponse{IsAuthorized: false}, nil
	}
	ssmClient := ssm.NewFromConfig(awsCfg)

	header := req.Headers["authorization"]
	if header == "" {
		header = req.Headers["Authorization"]
	}
	if len(header) < 8 || header[:7] != "Bearer " {
		return events.APIGatewayV2CustomAuthorizerSimpleResponse{IsAuthorized: false}, nil
	}
	token := header[7:]

	subject, err := auth.VerifyJWT(ctx, ssmClient, token)
	if err != nil {
		log.Printf("verify jwt: %v", err)
		return events.APIGatewayV2CustomAuthorizerSimpleResponse{IsAuthorized: false}, nil
	}

	return events.APIGatewayV2CustomAuthorizerSimpleResponse{
		IsAuthorized: true,
		Context: map[string]interface{}{
			"subject": subject,
		},
	}, nil
}

func main() {
	lambda.Start(handler)
}
