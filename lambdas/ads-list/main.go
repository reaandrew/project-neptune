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

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

type adSummary struct {
	AdID       string `json:"adId"`
	BrandJobID string `json:"brandJobId,omitempty"`
	Status     string `json:"status"`
	Headline   string `json:"headline,omitempty"`
	CreatedAt  string `json:"createdAt,omitempty"`
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
	if jobsTable == "" {
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
		ProjectionExpression: aws.String("ad_id, brand_job_id, #s, headline, created_at, subject"),
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

	ads := make([]adSummary, 0, len(items))
	for _, it := range items {
		ads = append(ads, adSummary{
			AdID:       sval(it, "ad_id"),
			BrandJobID: sval(it, "brand_job_id"),
			Status:     sval(it, "status"),
			Headline:   sval(it, "headline"),
			CreatedAt:  sval(it, "created_at"),
		})
	}
	sort.Slice(ads, func(i, j int) bool {
		return ads[i].CreatedAt > ads[j].CreatedAt
	})
	if len(ads) > 100 {
		ads = ads[:100]
	}

	return jsonResp(200, listResponse{Ads: ads}), nil
}

func main() {
	lambda.Start(handler)
}
