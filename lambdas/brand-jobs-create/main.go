// POST /brand-jobs {url, force?}
//
// Creates a "pending" job row in DDB, fires an async Lambda invoke at
// the brand-worker container function, and returns the job id. The
// caller polls GET /brand-jobs/{id} for status + signed PDF URL.
//
// Caching: unless `force: true` is passed, we look up the most-recent
// `done` job for the same normalised URL via the url-index GSI. If one
// exists we return its jobId (HTTP 200 + cached:true) instead of
// re-running the ~$3 pipeline.
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
	URL   string `json:"url"`
	Force bool   `json:"force"`
}

type responseBody struct {
	JobID  string `json:"jobId"`
	Cached bool   `json:"cached,omitempty"`
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

// normaliseURL collapses cosmetic differences so the cache hits even
// when the user types "WWW.example.com" vs "example.com/".
//
// Rules: lowercase scheme + host, strip leading "www.", ensure a path
// (so "/" and "" both become "/"), drop fragment + query.
func normaliseURL(raw string) string {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return strings.ToLower(strings.TrimSpace(raw))
	}
	scheme := strings.ToLower(u.Scheme)
	host := strings.ToLower(u.Host)
	host = strings.TrimPrefix(host, "www.")
	path := u.Path
	if path == "" {
		path = "/"
	}
	return scheme + "://" + host + path
}

// findCachedJob returns the jobId of the most-recent `done` job for the
// given normalised URL OWNED BY THIS SUBJECT, or "" if none. The cache
// is per-user — User B registering the same URL gets their own job,
// not User A's.
func findCachedJob(ctx context.Context, ddb *dynamodb.Client, jobsTable, urlNorm, subject string) string {
	if subject == "" {
		// Without a subject we can't safely cache-hit. Treat as miss.
		return ""
	}
	out, err := ddb.Query(ctx, &dynamodb.QueryInput{
		TableName:              aws.String(jobsTable),
		IndexName:              aws.String("url-index"),
		KeyConditionExpression: aws.String("url_normalised = :u"),
		FilterExpression:       aws.String("subject = :sub AND #s = :done"),
		ExpressionAttributeNames: map[string]string{
			"#s": "status",
		},
		ExpressionAttributeValues: map[string]ddbtypes.AttributeValue{
			":u":    &ddbtypes.AttributeValueMemberS{Value: urlNorm},
			":sub":  &ddbtypes.AttributeValueMemberS{Value: subject},
			":done": &ddbtypes.AttributeValueMemberS{Value: "done"},
		},
		ScanIndexForward: aws.Bool(false), // newest created_at first
		Limit:            aws.Int32(10),
	})
	if err != nil {
		log.Printf("cache lookup: %v", err)
		return ""
	}
	for _, item := range out.Items {
		jobID, _ := item["job_id"].(*ddbtypes.AttributeValueMemberS)
		if jobID != nil && jobID.Value != "" {
			return jobID.Value
		}
	}
	return ""
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
	urlNorm := normaliseURL(target)

	subject := ""
	if req.RequestContext.Authorizer != nil && req.RequestContext.Authorizer.Lambda != nil {
		if s, ok := req.RequestContext.Authorizer.Lambda["subject"].(string); ok {
			subject = s
		}
	}
	if subject == "" {
		return errResp(401, "unauthenticated"), nil
	}

	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return errResp(500, "internal error"), nil
	}
	ddb := dynamodb.NewFromConfig(awsCfg)
	lam := awslambda.NewFromConfig(awsCfg)

	// Cache hit? Per-user — different users get separate brand jobs
	// for the same URL.
	if !body.Force {
		if cachedID := findCachedJob(ctx, ddb, jobsTable, urlNorm, subject); cachedID != "" {
			return jsonResp(200, responseBody{JobID: cachedID, Cached: true}), nil
		}
	}

	jobID := newID()
	now := time.Now().UTC().Format(time.RFC3339)
	// TTL: drop the DDB row after 90 days. Matches the S3 lifecycle for
	// brand-jobs/ artifacts.
	ttl := time.Now().Add(90 * 24 * time.Hour).Unix()

	_, err = ddb.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: aws.String(jobsTable),
		Item: map[string]ddbtypes.AttributeValue{
			"job_id":         &ddbtypes.AttributeValueMemberS{Value: jobID},
			"url":            &ddbtypes.AttributeValueMemberS{Value: target},
			"url_normalised": &ddbtypes.AttributeValueMemberS{Value: urlNorm},
			"status":         &ddbtypes.AttributeValueMemberS{Value: "pending"},
			"created_at":     &ddbtypes.AttributeValueMemberS{Value: now},
			"subject":        &ddbtypes.AttributeValueMemberS{Value: subject},
			"expires_at":     &ddbtypes.AttributeValueMemberN{Value: fmt.Sprintf("%d", ttl)},
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
