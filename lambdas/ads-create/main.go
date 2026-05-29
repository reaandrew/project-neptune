// POST /ads
//
// Creates a "pending" ads-job row, fires an async invoke at the
// ads-worker container function, returns {adJobId}. Caller polls
// GET /ads/{id} for status + signed PNG URL.
//
// Body shape:
//   {
//     "brandJobId": "...",       // existing brand-jobs jobId, required
//     "headline":   "...",       // optional
//     "body":       "...",       // optional supporting copy
//     "cta":        "...",       // optional call-to-action
//     "sampleAdUrl":"https://...",// optional style reference
//     // Creative-brief dimensions — all optional, blank/empty == auto:
//     "platform":   "facebook-feed",
//     "objective":  "get-leads",
//     "layout":     "single-hero",
//     "angle":      "benefit-led",
//     "elements":   ["logo","headline","cta","website"]
//   }
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
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
	BrandJobID  string   `json:"brandJobId"`
	Headline    string   `json:"headline"`
	Body        string   `json:"body"`
	CTA         string   `json:"cta"`
	SampleAdURL string   `json:"sampleAdUrl"`
	// Creative-brief dimensions. All optional — empty string means
	// "auto / let the worker pick". `Elements` empty means use the
	// worker's default mix (logo, headline, CTA, website).
	Platform  string   `json:"platform"`
	Objective string   `json:"objective"`
	Layout    string   `json:"layout"`
	Angle     string   `json:"angle"`
	Elements  []string `json:"elements"`
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

func handler(ctx context.Context, req events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {
	jobsTable := os.Getenv("ADS_JOBS_TABLE")
	brandTable := os.Getenv("BRAND_JOBS_TABLE")
	workerFn := os.Getenv("WORKER_FUNCTION_NAME")
	if jobsTable == "" || brandTable == "" || workerFn == "" {
		return errResp(500, "service misconfigured"), nil
	}

	var body requestBody
	if err := json.Unmarshal([]byte(req.Body), &body); err != nil {
		return errResp(400, "invalid json"), nil
	}
	body.BrandJobID = strings.TrimSpace(body.BrandJobID)
	if body.BrandJobID == "" {
		return errResp(400, "brandJobId required"), nil
	}

	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return errResp(500, "internal error"), nil
	}
	ddb := dynamodb.NewFromConfig(awsCfg)
	lam := awslambda.NewFromConfig(awsCfg)

	// Verify the brand job is done — no point firing the worker against
	// a job that doesn't exist or hasn't rendered yet.
	bj, err := ddb.GetItem(ctx, &dynamodb.GetItemInput{
		TableName: aws.String(brandTable),
		Key: map[string]ddbtypes.AttributeValue{
			"job_id": &ddbtypes.AttributeValueMemberS{Value: body.BrandJobID},
		},
	})
	if err != nil || len(bj.Item) == 0 {
		return errResp(404, "brand job not found"), nil
	}
	var status string
	if s, ok := bj.Item["status"].(*ddbtypes.AttributeValueMemberS); ok {
		status = s.Value
	}
	if status != "done" {
		return errResp(409, "brand job not ready (status: "+status+")"), nil
	}

	adID := newID()
	now := time.Now().UTC().Format(time.RFC3339)
	ttl := time.Now().Add(7 * 24 * time.Hour).Unix()

	subject := ""
	if req.RequestContext.Authorizer != nil && req.RequestContext.Authorizer.Lambda != nil {
		if s, ok := req.RequestContext.Authorizer.Lambda["subject"].(string); ok {
			subject = s
		}
	}

	item := map[string]ddbtypes.AttributeValue{
		"ad_id":        &ddbtypes.AttributeValueMemberS{Value: adID},
		"brand_job_id": &ddbtypes.AttributeValueMemberS{Value: body.BrandJobID},
		"status":       &ddbtypes.AttributeValueMemberS{Value: "pending"},
		"created_at":   &ddbtypes.AttributeValueMemberS{Value: now},
		"subject":      &ddbtypes.AttributeValueMemberS{Value: subject},
		"expires_at":   &ddbtypes.AttributeValueMemberN{Value: fmt.Sprintf("%d", ttl)},
	}
	if body.Headline != "" {
		item["headline"] = &ddbtypes.AttributeValueMemberS{Value: body.Headline}
	}
	if body.Body != "" {
		item["body"] = &ddbtypes.AttributeValueMemberS{Value: body.Body}
	}
	if body.CTA != "" {
		item["cta"] = &ddbtypes.AttributeValueMemberS{Value: body.CTA}
	}
	if body.SampleAdURL != "" {
		item["sample_ad_url"] = &ddbtypes.AttributeValueMemberS{Value: body.SampleAdURL}
	}
	if body.Platform != "" {
		item["platform"] = &ddbtypes.AttributeValueMemberS{Value: body.Platform}
	}
	if body.Objective != "" {
		item["objective"] = &ddbtypes.AttributeValueMemberS{Value: body.Objective}
	}
	if body.Layout != "" {
		item["layout"] = &ddbtypes.AttributeValueMemberS{Value: body.Layout}
	}
	if body.Angle != "" {
		item["angle"] = &ddbtypes.AttributeValueMemberS{Value: body.Angle}
	}
	if len(body.Elements) > 0 {
		els := make([]ddbtypes.AttributeValue, 0, len(body.Elements))
		for _, e := range body.Elements {
			if e == "" {
				continue
			}
			els = append(els, &ddbtypes.AttributeValueMemberS{Value: e})
		}
		if len(els) > 0 {
			item["elements"] = &ddbtypes.AttributeValueMemberL{Value: els}
		}
	}

	if _, err := ddb.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: aws.String(jobsTable),
		Item:      item,
	}); err != nil {
		log.Printf("ddb put: %v", err)
		return errResp(500, "could not enqueue ad job"), nil
	}

	payload, _ := json.Marshal(map[string]any{
		"adId":        adID,
		"brandJobId":  body.BrandJobID,
		"headline":    body.Headline,
		"body":        body.Body,
		"cta":         body.CTA,
		"sampleAdUrl": body.SampleAdURL,
		"platform":    body.Platform,
		"objective":   body.Objective,
		"layout":      body.Layout,
		"angle":       body.Angle,
		"elements":    body.Elements,
	})
	if _, err := lam.Invoke(ctx, &awslambda.InvokeInput{
		FunctionName:   aws.String(workerFn),
		InvocationType: types.InvocationTypeEvent,
		Payload:        payload,
	}); err != nil {
		log.Printf("invoke worker: %v", err)
		_, _ = ddb.UpdateItem(ctx, &dynamodb.UpdateItemInput{
			TableName: aws.String(jobsTable),
			Key:       map[string]ddbtypes.AttributeValue{"ad_id": &ddbtypes.AttributeValueMemberS{Value: adID}},
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

	return jsonResp(202, map[string]string{"adId": adID}), nil
}

func main() {
	lambda.Start(handler)
}
