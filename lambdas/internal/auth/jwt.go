// Package auth verifies the JWT issued by reaandrew/ara on passkey
// login. We trust the same HS256 secret stored at /ara/jwt-signing-key
// (set the SSM path via the JWT_SIGNING_KEY_PARAM env var).
package auth

import (
	"context"
	"fmt"
	"os"
	"sync"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/golang-jwt/jwt/v5"
)

var (
	signingKey     []byte
	signingKeyOnce sync.Once
	signingKeyErr  error
)

func loadSigningKey(ctx context.Context, ssmClient *ssm.Client) ([]byte, error) {
	signingKeyOnce.Do(func() {
		paramName := os.Getenv("JWT_SIGNING_KEY_PARAM")
		if paramName == "" {
			signingKeyErr = fmt.Errorf("JWT_SIGNING_KEY_PARAM not set")
			return
		}
		out, err := ssmClient.GetParameter(ctx, &ssm.GetParameterInput{
			Name:           aws.String(paramName),
			WithDecryption: aws.Bool(true),
		})
		if err != nil {
			signingKeyErr = fmt.Errorf("get signing key: %w", err)
			return
		}
		signingKey = []byte(aws.ToString(out.Parameter.Value))
	})
	return signingKey, signingKeyErr
}

// VerifyJWT parses and validates a token, returning its subject claim.
// Subject = base64url(passkey credential id) as set by ara.
func VerifyJWT(ctx context.Context, ssmClient *ssm.Client, tokenString string) (string, error) {
	key, err := loadSigningKey(ctx, ssmClient)
	if err != nil {
		return "", err
	}
	parsed, err := jwt.ParseWithClaims(tokenString, &jwt.RegisteredClaims{}, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return key, nil
	})
	if err != nil {
		return "", err
	}
	claims, ok := parsed.Claims.(*jwt.RegisteredClaims)
	if !ok || !parsed.Valid {
		return "", fmt.Errorf("invalid token")
	}
	return claims.Subject, nil
}
