// GET /ads/{id}
// Returns ad-job status + presigned PNG URL when done.
package main

import (
	"context"
	"encoding/json"
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
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type adResponse struct {
	AdID        string `json:"adId"`
	BrandJobID  string `json:"brandJobId,omitempty"`
	Status      string `json:"status"`
	Headline    string `json:"headline,omitempty"`
	Body        string `json:"body,omitempty"`
	CTA         string `json:"cta,omitempty"`
	ImageURL    string `json:"imageUrl,omitempty"`
	Error       string `json:"error,omitempty"`
	CreatedAt   string `json:"createdAt,omitempty"`
	CompletedAt string `json:"completedAt,omitempty"`
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
	adID := strings.TrimSpace(req.PathParameters["id"])
	if adID == "" {
		return errResp(400, "missing ad id"), nil
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

	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return errResp(500, "internal error"), nil
	}
	ddb := dynamodb.NewFromConfig(awsCfg)

	out, err := ddb.GetItem(ctx, &dynamodb.GetItemInput{
		TableName: aws.String(jobsTable),
		Key: map[string]ddbtypes.AttributeValue{
			"ad_id": &ddbtypes.AttributeValueMemberS{Value: adID},
		},
	})
	if err != nil {
		log.Printf("ddb get: %v", err)
		return errResp(500, "internal error"), nil
	}
	if len(out.Item) == 0 {
		return errResp(404, "not found"), nil
	}
	if owner := sval(out.Item, "subject"); owner != "" && owner != subject {
		return errResp(404, "not found"), nil
	}

	resp := adResponse{
		AdID:        adID,
		BrandJobID:  sval(out.Item, "brand_job_id"),
		Status:      sval(out.Item, "status"),
		Headline:    sval(out.Item, "headline"),
		Body:        sval(out.Item, "body"),
		CTA:         sval(out.Item, "cta"),
		Error:       sval(out.Item, "error"),
		CreatedAt:   sval(out.Item, "created_at"),
		CompletedAt: sval(out.Item, "completed_at"),
	}

	if resp.Status == "done" {
		key := sval(out.Item, "image_key")
		if key == "" {
			key = "ads/" + adID + ".png"
		}
		s3Client := s3.NewFromConfig(awsCfg)
		presigner := s3.NewPresignClient(s3Client)
		r, err := presigner.PresignGetObject(ctx, &s3.GetObjectInput{
			Bucket: aws.String(artifactsBucket),
			Key:    aws.String(key),
		}, s3.WithPresignExpires(15*time.Minute))
		if err != nil {
			log.Printf("presign: %v", err)
			return errResp(500, "could not sign image url"), nil
		}
		resp.ImageURL = r.URL
	}

	return jsonResp(200, resp), nil
}

func main() {
	lambda.Start(handler)
}
