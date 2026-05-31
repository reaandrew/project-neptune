// GET /brand-jobs
//
// Returns the caller's brand jobs, newest-first, capped to 50. The
// table is small enough that a filtered scan is the simplest and
// cheapest pattern; if it ever grows we can add a subject-indexed GSI.
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/url"
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

// normaliseURL collapses cosmetic differences (case, www prefix, query
// string) so two registrations of the same brand land in the same
// dedup bucket. Mirrors the rule used in brand-jobs-create so the
// dashboard view matches what the URL cache treats as equivalent.
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

// statusRank ranks job statuses so we can prefer "done" over
// "running"/"pending" when picking the canonical entry per URL.
func statusRank(s string) int {
	switch s {
	case "done":
		return 3
	case "running":
		return 2
	case "pending":
		return 1
	default:
		return 0
	}
}

type jobSummary struct {
	JobID         string `json:"jobId"`
	URL           string `json:"url,omitempty"`
	Status        string `json:"status"`
	CreatedAt     string `json:"createdAt,omitempty"`
	BrandName     string `json:"brandName,omitempty"`
	PrimaryColor  string `json:"primaryColor,omitempty"`
	LogoURL       string `json:"logoUrl,omitempty"`
	ScreenshotURL string `json:"screenshotUrl,omitempty"`
}

type listResponse struct {
	Jobs []jobSummary `json:"jobs"`
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

	subject := ""
	if req.RequestContext.Authorizer != nil && req.RequestContext.Authorizer.Lambda != nil {
		if s, ok := req.RequestContext.Authorizer.Lambda["subject"].(string); ok {
			subject = s
		}
	}
	if subject == "" {
		// Refuse to return brand-jobs when we can't identify the
		// caller — otherwise this leaks everyone's brands.
		return errResp(401, "unauthenticated"), nil
	}

	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("aws config: %v", err)
		return errResp(500, "internal error"), nil
	}
	ddb := dynamodb.NewFromConfig(awsCfg)

	input := &dynamodb.ScanInput{
		TableName: aws.String(jobsTable),
		ProjectionExpression: aws.String(
			"job_id, #u, #s, created_at, subject, brand_name, primary_color, logo_url, screenshot_key, url_normalised",
		),
		ExpressionAttributeNames: map[string]string{
			"#u": "url",
			"#s": "status",
		},
		FilterExpression: aws.String("subject = :sub"),
		ExpressionAttributeValues: map[string]ddbtypes.AttributeValue{
			":sub": &ddbtypes.AttributeValueMemberS{Value: subject},
		},
	}

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

	jobs := make([]jobSummary, 0, len(items))
	for _, it := range items {
		jobs = append(jobs, jobSummary{
			JobID:        sval(it, "job_id"),
			URL:          sval(it, "url"),
			Status:       sval(it, "status"),
			CreatedAt:    sval(it, "created_at"),
			BrandName:    sval(it, "brand_name"),
			PrimaryColor: sval(it, "primary_color"),
			LogoURL:      sval(it, "logo_url"),
		})
	}

	// Deduplicate by normalised URL — one card per brand, not one card
	// per scan. Without this, every Regenerate click leaves a stale
	// row visible in the dashboard. Prefer status=done, then most
	// recent createdAt.
	urlNormalisedByJobID := map[string]string{}
	for _, it := range items {
		jobID := sval(it, "job_id")
		nu := sval(it, "url_normalised")
		if nu == "" {
			// Backfill old rows that predate the url_normalised
			// field — normalise on the fly.
			nu = normaliseURL(sval(it, "url"))
		}
		urlNormalisedByJobID[jobID] = nu
	}
	bestByURL := map[string]int{}  // url_normalised → index into jobs
	for i, j := range jobs {
		nu := urlNormalisedByJobID[j.JobID]
		if nu == "" {
			// Fall back to the raw jobId so we don't accidentally
			// collapse multiple URL-less rows into one bucket.
			nu = "__no-url__" + j.JobID
		}
		current, ok := bestByURL[nu]
		if !ok {
			bestByURL[nu] = i
			continue
		}
		// Prefer higher status rank; break ties by most recent.
		curRank := statusRank(jobs[current].Status)
		newRank := statusRank(j.Status)
		if newRank > curRank ||
			(newRank == curRank && j.CreatedAt > jobs[current].CreatedAt) {
			bestByURL[nu] = i
		}
	}
	deduped := make([]jobSummary, 0, len(bestByURL))
	for _, idx := range bestByURL {
		deduped = append(deduped, jobs[idx])
	}
	jobs = deduped

	sort.Slice(jobs, func(i, j int) bool {
		return jobs[i].CreatedAt > jobs[j].CreatedAt
	})
	if len(jobs) > 50 {
		jobs = jobs[:50]
	}

	// Presign the homepage screenshots so the frontend can render them
	// directly as <img>. We grab the matching screenshot_key from the
	// scanned items rather than re-fetching from DDB.
	keysByJob := map[string]string{}
	for _, it := range items {
		keysByJob[sval(it, "job_id")] = sval(it, "screenshot_key")
	}
	s3Client := s3.NewFromConfig(awsCfg)
	presigner := s3.NewPresignClient(s3Client)
	for i := range jobs {
		key := keysByJob[jobs[i].JobID]
		if key == "" {
			continue
		}
		r, err := presigner.PresignGetObject(ctx, &s3.GetObjectInput{
			Bucket: aws.String(artifactsBucket),
			Key:    aws.String(key),
		}, s3.WithPresignExpires(15*time.Minute))
		if err != nil {
			log.Printf("presign %s: %v", key, err)
			continue
		}
		jobs[i].ScreenshotURL = r.URL
	}

	return jsonResp(200, listResponse{Jobs: jobs}), nil
}

func main() {
	lambda.Start(handler)
}
