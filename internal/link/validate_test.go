package link

import (
	"errors"
	"strings"
	"testing"
)

func TestValidateURL(t *testing.T) {
	tests := []struct {
		name    string
		url     string
		wantErr error // nil = valid
	}{
		{"https", "https://go.dev/doc", nil},
		{"http with port and query", "http://example.com:8080/a?b=c&d=e", nil},
		{"uppercase scheme", "HTTPS://EXAMPLE.COM", nil},
		{"exactly 2048 chars", "https://x.com/" + strings.Repeat("a", MaxURLLength-len("https://x.com/")), nil},
		{"empty", "", ErrInvalidURL},
		{"not a url", "not a url", ErrInvalidURL},
		{"scheme only", "http://", ErrInvalidURL},
		{"port but no host", "http://:80", ErrInvalidURL},
		{"ftp", "ftp://example.com", ErrInvalidURL},
		{"javascript", "javascript:alert(1)", ErrInvalidURL},
		{"data", "data:text/html,<script>alert(1)</script>", ErrInvalidURL},
		{"relative path", "/just/a/path", ErrInvalidURL},
		{"2049 chars", "https://x.com/" + strings.Repeat("a", MaxURLLength-len("https://x.com/")+1), ErrInvalidURL},
		{"control character", "https://x.com/\nSet-Cookie:a=b", ErrInvalidURL},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateURL(tt.url)
			if tt.wantErr == nil {
				if err != nil {
					t.Fatalf("ValidateURL(%q) = %v, want nil", tt.url, err)
				}
				return
			}
			if !errors.Is(err, tt.wantErr) {
				t.Fatalf("ValidateURL(%q) = %v, want errors.Is(%v)", tt.url, err, tt.wantErr)
			}
		})
	}
}

func TestValidateCode(t *testing.T) {
	tests := []struct {
		name    string
		code    string
		wantErr error
	}{
		{"min length", "abc", nil},
		{"max length", strings.Repeat("a", 32), nil},
		{"dash and underscore", "go-docs_v2", nil},
		{"mixed case digits", "AbC123", nil},
		{"too short", "ab", ErrInvalidCode},
		{"too long", strings.Repeat("a", 33), ErrInvalidCode},
		{"space and bang", "bad code!", ErrInvalidCode},
		{"slash", "a/b/c", ErrInvalidCode},
		{"non ascii", "سلام", ErrInvalidCode},
		{"reserved api", "api", ErrInvalidCode},
		{"reserved healthz uppercase", "HEALTHZ", ErrInvalidCode},
		{"reserved readyz", "readyz", ErrInvalidCode},
		{"reserved metrics", "Metrics", ErrInvalidCode},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateCode(tt.code)
			if tt.wantErr == nil && err != nil {
				t.Fatalf("ValidateCode(%q) = %v, want nil", tt.code, err)
			}
			if tt.wantErr != nil && !errors.Is(err, tt.wantErr) {
				t.Fatalf("ValidateCode(%q) = %v, want errors.Is(%v)", tt.code, err, tt.wantErr)
			}
		})
	}
}
