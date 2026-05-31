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
	"sync"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
)

type jobResponse struct {
	JobID            string `json:"jobId"`
	Status           string `json:"status"`
	URL              string `json:"url,omitempty"`
	PDFURL           string `json:"pdfUrl,omitempty"`
	YAMLURL          string `json:"yamlUrl,omitempty"`
	JSONURL          string `json:"jsonUrl,omitempty"`
	ScreenshotURL    string `json:"screenshotUrl,omitempty"`
	TailwindURL      string `json:"tailwindConfigUrl,omitempty"`
	MUIThemeURL      string `json:"muiThemeUrl,omitempty"`
	BootstrapVarsURL string `json:"bootstrapVarsUrl,omitempty"`
	BrandName        string `json:"brandName,omitempty"`
	PrimaryColor     string `json:"primaryColor,omitempty"`
	LogoURL          string `json:"logoUrl,omitempty"`
	Error            string `json:"error,omitempty"`
	CreatedAt        string `json:"createdAt,omitempty"`
	CompletedAt      string `json:"completedAt,omitempty"`
	IsAdmin          bool   `json:"isAdmin,omitempty"`
}

// Admin-subject lookup cached for the lambda lifetime. Resolved on
// first request, not at package init, so an SSM hiccup at cold start
// is recoverable.
var (
	adminSubjectOnce sync.Once
	adminSubject     string
)

func loadAdminSubject(ctx context.Context, ssmClient *ssm.Client) string {
	adminSubjectOnce.Do(func() {
		name := os.Getenv("ADMIN_SUBJECT_PARAM")
		if name == "" {
			return
		}
		out, err := ssmClient.GetParameter(ctx, &ssm.GetParameterInput{
			Name: aws.String(name),
		})
		if err != nil {
			log.Printf("admin subject lookup: %v", err)
			return
		}
		if out.Parameter != nil && out.Parameter.Value != nil {
			adminSubject = *out.Parameter.Value
		}
	})
	return adminSubject
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
	// Ownership: 404 (not 403) so we don't leak existence to other
	// callers.
	if owner := sval(out.Item, "subject"); owner != "" && owner != subject {
		return errResp(404, "not found"), nil
	}

	ssmClient := ssm.NewFromConfig(awsCfg)
	admin := loadAdminSubject(ctx, ssmClient)

	resp := jobResponse{
		JobID:        jobID,
		Status:       sval(out.Item, "status"),
		URL:          sval(out.Item, "url"),
		BrandName:    sval(out.Item, "brand_name"),
		PrimaryColor: sval(out.Item, "primary_color"),
		LogoURL:      sval(out.Item, "logo_url"),
		Error:        sval(out.Item, "error"),
		CreatedAt:    sval(out.Item, "created_at"),
		CompletedAt:  sval(out.Item, "completed_at"),
		IsAdmin:      admin != "" && subject == admin,
	}

	if resp.Status == "done" {
		s3Client := s3.NewFromConfig(awsCfg)
		presigner := s3.NewPresignClient(s3Client)
		sign := func(key string) string {
			if key == "" {
				return ""
			}
			r, err := presigner.PresignGetObject(ctx, &s3.GetObjectInput{
				Bucket: aws.String(artifactsBucket),
				Key:    aws.String(key),
			}, s3.WithPresignExpires(15*time.Minute))
			if err != nil {
				log.Printf("presign %s: %v", key, err)
				return ""
			}
			return r.URL
		}
		pdfKey := sval(out.Item, "pdf_key")
		if pdfKey == "" {
			pdfKey = "brand-jobs/" + jobID + ".pdf"
		}
		resp.PDFURL = sign(pdfKey)
		resp.YAMLURL = sign(sval(out.Item, "yaml_key"))
		resp.JSONURL = sign(sval(out.Item, "json_key"))
		resp.ScreenshotURL = sign(sval(out.Item, "screenshot_key"))
		resp.TailwindURL = sign(sval(out.Item, "tailwind_key"))
		resp.MUIThemeURL = sign(sval(out.Item, "mui_theme_key"))
		resp.BootstrapVarsURL = sign(sval(out.Item, "bootstrap_vars_key"))
	}

	return jsonResp(200, resp), nil
}

func main() {
	lambda.Start(handler)
}
