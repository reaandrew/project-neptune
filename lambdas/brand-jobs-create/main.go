// POST /brand-jobs {url}
//
// Creates a "pending" job row in DDB, fires an async Lambda invoke at
// the brand-worker container function, and returns the job id. The
// caller polls GET /brand-jobs/{id} for status + signed PDF URL.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	awslambda "github.com/aws/aws-sdk-go-v2/service/lambda"
	"github.com/aws/aws-sdk-go-v2/service/lambda/types"
)

type requestBody struct {
	URL string `json:"url"`
}

type responseBody struct {
	JobID string `json:"jobId"`
}

func jsonResp(status int, body interface{}) events.APIGatewayV2HTTPResponse {
	b, _ := json.Marshal(body)
	return events.APIGatewayV2HTTPResponse{
		StatusCode: status,
		Headers:    map[string]string{"Content-Type": "application/json"},
		Body:       string(b),
	}
}

func errResp(status int, msg string) events.APIGatewayV2HTTPResponse {
	return jsonResp(status, map[string]string{"error": msg})
}

func newID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func isValidURL(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return false
	}
	if u.Host == "" {
		return false
	}
	return true
}

func handler(ctx context.Context, req events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {
	jobsTable := os.Getenv("JOBS_TABLE")
	workerFn := os.Getenv("WORKER_FUNCTION_NAME")
	if jobsTable == "" || workerFn == "" {
		return errResp(500, "service misconfigured"), nil
	}

	var body requestBody
	if err := json.Unmarshal([]byte(req.Body), &body); err != nil {
		return errResp(400, "invalid json"), nil
	}
	target := strings.TrimSpace(body.URL)
	if !isValidURL(target) {
		return errResp(400, "url must be http(s)"), nil
	}

	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return errResp(500, "internal error"), nil
	}
	ddb := dynamodb.NewFromConfig(awsCfg)
	lam := awslambda.NewFromConfig(awsCfg)

	jobID := newID()
	now := time.Now().UTC().Format(time.RFC3339)
	// TTL: drop the DDB row after 7 days. Matches the S3 lifecycle.
	ttl := time.Now().Add(7 * 24 * time.Hour).Unix()

	subject := ""
	if req.RequestContext.Authorizer != nil && req.RequestContext.Authorizer.Lambda != nil {
		if s, ok := req.RequestContext.Authorizer.Lambda["subject"].(string); ok {
			subject = s
		}
	}

	_, err = ddb.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: aws.String(jobsTable),
		Item: map[string]ddbtypes.AttributeValue{
			"job_id":     &ddbtypes.AttributeValueMemberS{Value: jobID},
			"url":        &ddbtypes.AttributeValueMemberS{Value: target},
			"status":     &ddbtypes.AttributeValueMemberS{Value: "pending"},
			"created_at": &ddbtypes.AttributeValueMemberS{Value: now},
			"subject":    &ddbtypes.AttributeValueMemberS{Value: subject},
			"expires_at": &ddbtypes.AttributeValueMemberN{Value: fmt.Sprintf("%d", ttl)},
		},
	})
	if err != nil {
		log.Printf("ddb put: %v", err)
		return errResp(500, "could not enqueue job"), nil
	}

	payload, _ := json.Marshal(map[string]string{"jobId": jobID, "url": target})
	_, err = lam.Invoke(ctx, &awslambda.InvokeInput{
		FunctionName:   aws.String(workerFn),
		InvocationType: types.InvocationTypeEvent, // async
		Payload:        payload,
	})
	if err != nil {
		log.Printf("invoke worker: %v", err)
		// Mark the row so the poller surfaces the failure.
		_, _ = ddb.UpdateItem(ctx, &dynamodb.UpdateItemInput{
			TableName: aws.String(jobsTable),
			Key:       map[string]ddbtypes.AttributeValue{"job_id": &ddbtypes.AttributeValueMemberS{Value: jobID}},
			UpdateExpression: aws.String("SET #s = :s, #e = :e"),
			ExpressionAttributeNames: map[string]string{
				"#s": "status",
				"#e": "error",
			},
			ExpressionAttributeValues: map[string]ddbtypes.AttributeValue{
				":s": &ddbtypes.AttributeValueMemberS{Value: "error"},
				":e": &ddbtypes.AttributeValueMemberS{Value: "worker dispatch failed"},
			},
		})
		return errResp(502, "could not start worker"), nil
	}

	return jsonResp(202, responseBody{JobID: jobID}), nil
}

func main() {
	lambda.Start(handler)
}
