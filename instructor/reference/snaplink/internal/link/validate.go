package link

import (
	"fmt"
	"net/url"
	"strings"
)

const (
	MaxURLLength  = 2048
	MinCodeLength = 3
	MaxCodeLength = 32
	MaxTTLSeconds = 365 * 24 * 60 * 60 // 31536000 = one year
)

// reserved are first path segments the service itself uses. A custom code with
// one of these names would be shadowed by (or would shadow) a real route.
var reserved = map[string]bool{
	"api":     true,
	"healthz": true,
	"readyz":  true,
	"metrics": true,
}

// IsReserved reports whether code is a reserved word (case-insensitive).
func IsReserved(code string) bool {
	return reserved[strings.ToLower(code)]
}

// ValidateURL accepts only absolute http(s) URLs with a host, at most 2048
// bytes long. Rejecting every other scheme (javascript:, data:, file:, ftp:)
// stops the shortener from being used to hide XSS payloads or odd redirects.
func ValidateURL(raw string) error {
	if raw == "" {
		return fmt.Errorf("%w: url is required", ErrInvalidURL)
	}
	if len(raw) > MaxURLLength {
		return fmt.Errorf("%w: longer than %d characters", ErrInvalidURL, MaxURLLength)
	}
	u, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("%w: cannot parse", ErrInvalidURL)
	}
	switch strings.ToLower(u.Scheme) {
	case "http", "https":
	default:
		return fmt.Errorf("%w: scheme must be http or https", ErrInvalidURL)
	}
	// Hostname() (not Host) so that "http://:80" is rejected as well.
	if u.Hostname() == "" {
		return fmt.Errorf("%w: host is required", ErrInvalidURL)
	}
	return nil
}

// ValidateCode checks a custom code: 3..32 characters from [A-Za-z0-9_-] and
// not a reserved word.
func ValidateCode(code string) error {
	if len(code) < MinCodeLength || len(code) > MaxCodeLength {
		return fmt.Errorf("%w: must be %d to %d characters", ErrInvalidCode, MinCodeLength, MaxCodeLength)
	}
	for _, c := range code {
		if !isCodeChar(c) {
			return fmt.Errorf("%w: only letters, digits, '-' and '_' are allowed", ErrInvalidCode)
		}
	}
	if IsReserved(code) {
		return fmt.Errorf("%w: %q is reserved", ErrInvalidCode, code)
	}
	return nil
}

// ValidateTTL checks ttl_seconds: a whole number from 1 to one year.
func ValidateTTL(seconds int64) error {
	if seconds < 1 || seconds > MaxTTLSeconds {
		return fmt.Errorf("%w: must be between 1 and %d", ErrInvalidTTL, MaxTTLSeconds)
	}
	return nil
}

func isCodeChar(c rune) bool {
	return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_'
}
