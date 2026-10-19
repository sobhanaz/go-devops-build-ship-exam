// Package link holds the SnapLink domain: the Link type, its validation rules,
// the short-code generator and the sentinel errors. It knows nothing about HTTP
// or Redis, so it is trivial to unit test.
package link

import (
	"errors"
	"time"
)

// Sentinel errors. Callers compare with errors.Is; the API layer maps them to
// HTTP status codes in exactly one place (api.statusFor).
var (
	ErrInvalidURL  = errors.New("invalid url")
	ErrInvalidCode = errors.New("invalid code")
	ErrCodeTaken   = errors.New("code already taken")
	ErrNotFound    = errors.New("link not found")
	ErrInvalidTTL  = errors.New("invalid ttl_seconds")
)

// Link is one short link. ShortURL is not stored: it depends on BASE_URL and
// is filled in by the API layer right before the link is written as JSON.
type Link struct {
	Code      string     `json:"code"`
	URL       string     `json:"url"`
	ShortURL  string     `json:"short_url"`
	Clicks    int64      `json:"clicks"`
	CreatedAt time.Time  `json:"created_at"`
	ExpiresAt *time.Time `json:"expires_at,omitempty"` // nil = never expires
}

// Expired reports whether the link has a TTL that has run out at now.
func (l Link) Expired(now time.Time) bool {
	return l.ExpiresAt != nil && !now.Before(*l.ExpiresAt)
}
