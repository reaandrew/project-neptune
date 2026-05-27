// GET /message — returns the welcome message rendered by the frontend.
// Demonstrates the client → BFF → API hop with no dependencies of its
// own; the authorizer in front of API Gateway has already verified the
// caller's JWT before this handler runs.
package main

import (
	"context"
	"encoding/json"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
)

type response struct {
	Message string `json:"message"`
}

func handler(_ context.Context, _ events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {
	body, _ := json.Marshal(response{Message: "Hello from project-neptune API"})
	return events.APIGatewayV2HTTPResponse{
		StatusCode: 200,
		Headers:    map[string]string{"Content-Type": "application/json"},
		Body:       string(body),
	}, nil
}

func main() {
	lambda.Start(handler)
}
