// GET /ads?brandJobId=<id>
//
// Returns the caller's ad jobs, newest-first, optionally scoped to a
// particular brand. Small table → filtered scan is fine.
package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type adSummary struct {
	AdID       string `json:"adId"`
	BrandJobID string `json:"brandJobId,omitempty"`
	Status     string `json:"status"`
	Headline   string `json:"headline,omitempty"`
	CreatedAt  string `json:"createdAt,omitempty"`
	ImageURL   string `json:"imageUrl,omitempty"`
}

type listResponse struct {
	Ads []adSummary `json:"ads"`
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

func sval(m map[string]ddbtypes.AttributeValue, k string) string {
	v, ok := m[k]
	if !ok {
		return ""
	}
	s, ok := v.(*ddbtypes.AttributeValueMemberS)
	if !ok {
		return ""
	}
	return s.Value
}

func handler(ctx context.Context, req events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {
	jobsTable := os.Getenv("ADS_JOBS_TABLE")
	artifactsBucket := os.Getenv("ARTIFACTS_BUCKET")
	if jobsTable == "" || artifactsBucket == "" {
		return errResp(500, "service misconfigured"), nil
	}

	subject := ""
	if req.RequestContext.Authorizer != nil && req.RequestContext.Authorizer.Lambda != nil {
		if s, ok := req.RequestContext.Authorizer.Lambda["subject"].(string); ok {
			subject = s
		}
	}
	if subject == "" {
		return errResp(401, "unauthenticated"), nil
	}
	brandJobID := strings.TrimSpace(req.QueryStringParameters["brandJobId"])

	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return errResp(500, "internal error"), nil
	}
	ddb := dynamodb.NewFromConfig(awsCfg)

	input := &dynamodb.ScanInput{
		TableName:            aws.String(jobsTable),
		ProjectionExpression: aws.String("ad_id, brand_job_id, #s, headline, created_at, subject, image_key"),
		ExpressionAttributeNames: map[string]string{
			"#s": "status",
		},
	}

	filters := []string{"subject = :sub"}
	values := map[string]ddbtypes.AttributeValue{
		":sub": &ddbtypes.AttributeValueMemberS{Value: subject},
	}
	if brandJobID != "" {
		filters = append(filters, "brand_job_id = :bid")
		values[":bid"] = &ddbtypes.AttributeValueMemberS{Value: brandJobID}
	}
	input.FilterExpression = aws.String(strings.Join(filters, " AND "))
	input.ExpressionAttributeValues = values

	var items []map[string]ddbtypes.AttributeValue
	paginator := dynamodb.NewScanPaginator(ddb, input)
	for paginator.HasMorePages() {
		out, err := paginator.NextPage(ctx)
		if err != nil {
			log.Printf("ddb scan: %v", err)
			return errResp(500, "internal error"), nil
		}
		items = append(items, out.Items...)
		if len(items) >= 200 {
			break
		}
	}

	type pending struct {
		summary  adSummary
		imageKey string
	}
	rows := make([]pending, 0, len(items))
	for _, it := range items {
		rows = append(rows, pending{
			summary: adSummary{
				AdID:       sval(it, "ad_id"),
				BrandJobID: sval(it, "brand_job_id"),
				Status:     sval(it, "status"),
				Headline:   sval(it, "headline"),
				CreatedAt:  sval(it, "created_at"),
			},
			imageKey: sval(it, "image_key"),
		})
	}
	sort.Slice(rows, func(i, j int) bool {
		return rows[i].summary.CreatedAt > rows[j].summary.CreatedAt
	})
	if len(rows) > 100 {
		rows = rows[:100]
	}

	// Presign thumbnails for done ads. Capped at 100 above so the
	// per-row sign cost is bounded.
	s3Client := s3.NewFromConfig(awsCfg)
	presigner := s3.NewPresignClient(s3Client)
	ads := make([]adSummary, 0, len(rows))
	for _, r := range rows {
		if r.summary.Status == "done" && r.imageKey != "" {
			pr, err := presigner.PresignGetObject(ctx, &s3.GetObjectInput{
				Bucket: aws.String(artifactsBucket),
				Key:    aws.String(r.imageKey),
			}, s3.WithPresignExpires(15*time.Minute))
			if err == nil {
				r.summary.ImageURL = pr.URL
			} else {
				log.Printf("presign %s: %v", r.imageKey, err)
			}
		}
		ads = append(ads, r.summary)
	}

	return jsonResp(200, listResponse{Ads: ads}), nil
}

func main() {
	lambda.Start(handler)
}
