// GET /brand-jobs/{id}
//
// Returns job status. If the job is `done` a 5-minute presigned S3 URL
// for the rendered PDF is included.
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

type jobResponse struct {
	JobID       string `json:"jobId"`
	Status      string `json:"status"`
	URL         string `json:"url,omitempty"`
	PDFURL      string `json:"pdfUrl,omitempty"`
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
	jobsTable := os.Getenv("JOBS_TABLE")
	artifactsBucket := os.Getenv("ARTIFACTS_BUCKET")
	if jobsTable == "" || artifactsBucket == "" {
		return errResp(500, "service misconfigured"), nil
	}

	jobID := strings.TrimSpace(req.PathParameters["id"])
	if jobID == "" {
		return errResp(400, "missing job id"), nil
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
			"job_id": &ddbtypes.AttributeValueMemberS{Value: jobID},
		},
	})
	if err != nil {
		log.Printf("ddb get: %v", err)
		return errResp(500, "internal error"), nil
	}
	if len(out.Item) == 0 {
		return errResp(404, "not found"), nil
	}

	resp := jobResponse{
		JobID:       jobID,
		Status:      sval(out.Item, "status"),
		URL:         sval(out.Item, "url"),
		Error:       sval(out.Item, "error"),
		CreatedAt:   sval(out.Item, "created_at"),
		CompletedAt: sval(out.Item, "completed_at"),
	}

	if resp.Status == "done" {
		s3Client := s3.NewFromConfig(awsCfg)
		presigner := s3.NewPresignClient(s3Client)
		key := sval(out.Item, "pdf_key")
		if key == "" {
			key = "brand-jobs/" + jobID + ".pdf"
		}
		req, err := presigner.PresignGetObject(ctx, &s3.GetObjectInput{
			Bucket: aws.String(artifactsBucket),
			Key:    aws.String(key),
		}, s3.WithPresignExpires(5*time.Minute))
		if err != nil {
			log.Printf("presign: %v", err)
			return errResp(500, "could not sign pdf url"), nil
		}
		resp.PDFURL = req.URL
	}

	return jsonResp(200, resp), nil
}

func main() {
	lambda.Start(handler)
}
