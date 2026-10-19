package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"snaplink/internal/link"
	"snaplink/internal/store"
)

const testBaseURL = "http://short.test"

func newTestServer(t *testing.T) (*Server, http.Handler) {
	t.Helper()
	logger := slog.New(slog.NewJSONHandler(io.Discard, nil))
	s := New(store.NewMemory(), testBaseURL+"/", logger)
	return s, s.Handler()
}

func do(t *testing.T, h http.Handler, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	var r io.Reader
	if body != "" {
		r = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, r)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decode[T any](t *testing.T, rec *httptest.ResponseRecorder) T {
	t.Helper()
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("Content-Type = %q, want application/json", ct)
	}
	var v T
	if err := json.Unmarshal(rec.Body.Bytes(), &v); err != nil {
		t.Fatalf("decode %q: %v", rec.Body.String(), err)
	}
	return v
}

func createLink(t *testing.T, h http.Handler, body string) link.Link {
	t.Helper()
	rec := do(t, h, http.MethodPost, "/api/links", body)
	if rec.Code != http.StatusCreated {
		t.Fatalf("POST /api/links %s = %d %s, want 201", body, rec.Code, rec.Body)
	}
	return decode[link.Link](t, rec)
}

func TestHealthz(t *testing.T) {
	_, h := newTestServer(t)
	rec := do(t, h, http.MethodGet, "/healthz", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := decode[map[string]string](t, rec); got["status"] != "ok" {
		t.Fatalf("body = %v", got)
	}
}

// downStore is a Store whose datastore is unreachable.
type downStore struct{ store.Store }

func (downStore) Ping(context.Context) error { return errors.New("connection refused") }

func TestReadyz(t *testing.T) {
	_, h := newTestServer(t)
	if rec := do(t, h, http.MethodGet, "/readyz", ""); rec.Code != http.StatusOK || decode[map[string]string](t, rec)["status"] != "ready" {
		t.Fatalf("ready store: %d %s", rec.Code, rec.Body)
	}

	down := New(downStore{store.NewMemory()}, testBaseURL, slog.New(slog.NewJSONHandler(io.Discard, nil))).Handler()
	rec := do(t, down, http.MethodGet, "/readyz", "")
	if rec.Code != http.StatusServiceUnavailable || decode[map[string]string](t, rec)["status"] != "not ready" {
		t.Fatalf("down store: %d %s, want 503 not ready", rec.Code, rec.Body)
	}
	// Liveness must not depend on the datastore.
	if rec := do(t, down, http.MethodGet, "/healthz", ""); rec.Code != http.StatusOK {
		t.Fatalf("healthz with down store = %d, want 200", rec.Code)
	}
}

func TestCreateLink(t *testing.T) {
	_, h := newTestServer(t)
	l := createLink(t, h, `{"url":"https://go.dev/doc?a=1&b=2"}`)
	if !regexp.MustCompile(`^[A-Za-z0-9]{6}$`).MatchString(l.Code) {
		t.Errorf("code = %q, want 6 base62 chars", l.Code)
	}
	if l.URL != "https://go.dev/doc?a=1&b=2" || l.Clicks != 0 || l.CreatedAt.IsZero() {
		t.Errorf("link = %+v", l)
	}
	if l.ShortURL != testBaseURL+"/"+l.Code {
		t.Errorf("short_url = %q, want %q", l.ShortURL, testBaseURL+"/"+l.Code)
	}

	custom := createLink(t, h, `{"url":"https://go.dev","code":"go-docs_1"}`)
	if custom.Code != "go-docs_1" {
		t.Errorf("custom code = %q", custom.Code)
	}
	rec := do(t, h, http.MethodPost, "/api/links", `{"url":"https://other.dev","code":"go-docs_1"}`)
	if rec.Code != http.StatusConflict || decode[errorResponse](t, rec).Error != "code already taken" {
		t.Fatalf("duplicate code = %d %s, want 409 code already taken", rec.Code, rec.Body)
	}
}

func TestCreateLinkBadRequest(t *testing.T) {
	_, h := newTestServer(t)
	createLink(t, h, `{"url":"https://go.dev","code":"taken"}`)

	tests := []struct {
		name string
		body string
	}{
		{"empty url", `{"url":""}`},
		{"missing url", `{}`},
		{"not a url", `{"url":"not a url"}`},
		{"no host", `{"url":"http://"}`},
		{"ftp", `{"url":"ftp://example.com"}`},
		{"javascript", `{"url":"javascript:alert(1)"}`},
		{"too long", fmt.Sprintf(`{"url":"https://x.com/%s"}`, strings.Repeat("a", 2049))},
		{"invalid json", `{"url":`},
		{"wrong type", `{"url":42}`},
		{"trailing data", `{"url":"https://go.dev"} {}`},
		{"code too short", `{"url":"https://go.dev","code":"ab"}`},
		{"code bad chars", `{"url":"https://go.dev","code":"bad code!"}`},
		{"code reserved", `{"url":"https://go.dev","code":"healthz"}`},
		{"code too long", `{"url":"https://go.dev","code":"` + strings.Repeat("a", 33) + `"}`},
		// 400 wins over 409: the code is taken, but the url is invalid.
		{"bad url with taken code", `{"url":"ftp://x","code":"taken"}`},
		{"ttl zero", `{"url":"https://go.dev","ttl_seconds":0}`},
		{"ttl negative", `{"url":"https://go.dev","ttl_seconds":-1}`},
		{"ttl fraction", `{"url":"https://go.dev","ttl_seconds":1.5}`},
		{"ttl string", `{"url":"https://go.dev","ttl_seconds":"10"}`},
		{"ttl over one year", `{"url":"https://go.dev","ttl_seconds":31536001}`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := do(t, h, http.MethodPost, "/api/links", tt.body)
			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d %s, want 400", rec.Code, rec.Body)
			}
			if decode[errorResponse](t, rec).Error == "" {
				t.Fatal(`want a non-empty "error" field`)
			}
		})
	}
}

func TestCreateLinkWithTTL(t *testing.T) {
	s, h := newTestServer(t)
	s.now = func() time.Time { return time.Date(2026, 10, 20, 9, 30, 0, 0, time.UTC) }

	rec := do(t, h, http.MethodPost, "/api/links", `{"url":"https://example.com/ttl","ttl_seconds":60}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d %s, want 201", rec.Code, rec.Body)
	}
	raw := decode[map[string]any](t, rec)
	if raw["expires_at"] != "2026-10-20T09:31:00Z" {
		t.Fatalf("expires_at = %v, want 2026-10-20T09:31:00Z", raw["expires_at"])
	}

	// Without a TTL the key is omitted entirely (omitempty on a pointer).
	rec = do(t, h, http.MethodPost, "/api/links", `{"url":"https://example.com/forever"}`)
	if _, ok := decode[map[string]any](t, rec)["expires_at"]; ok {
		t.Fatal("expires_at present on a link without ttl")
	}
}

func TestRedirectCountsClicks(t *testing.T) {
	_, h := newTestServer(t)
	l := createLink(t, h, `{"url":"https://example.com/target"}`)

	for i := 0; i < 2; i++ {
		rec := do(t, h, http.MethodGet, "/"+l.Code, "")
		if rec.Code != http.StatusFound || rec.Header().Get("Location") != l.URL {
			t.Fatalf("GET /%s = %d Location=%q, want 302 %q", l.Code, rec.Code, rec.Header().Get("Location"), l.URL)
		}
	}
	rec := do(t, h, http.MethodGet, "/api/links/"+l.Code, "")
	if got := decode[link.Link](t, rec); rec.Code != http.StatusOK || got.Clicks != 2 {
		t.Fatalf("GET /api/links/%s = %d clicks=%d, want 200 clicks=2", l.Code, rec.Code, got.Clicks)
	}

	for _, path := range []string{"/nOpE123456", "/api/links/nOpE123456"} {
		rec := do(t, h, http.MethodGet, path, "")
		if rec.Code != http.StatusNotFound || decode[errorResponse](t, rec).Error != "link not found" {
			t.Errorf("GET %s = %d %s, want 404 link not found", path, rec.Code, rec.Body)
		}
	}
}

func TestListLinks(t *testing.T) {
	s, h := newTestServer(t)
	rec := do(t, h, http.MethodGet, "/api/links", "")
	if rec.Code != http.StatusOK || strings.TrimSpace(rec.Body.String()) != "[]" {
		t.Fatalf("empty list = %d %q, want 200 []", rec.Code, rec.Body)
	}

	clock := time.Date(2026, 10, 20, 9, 30, 0, 0, time.UTC)
	s.now = func() time.Time { clock = clock.Add(time.Second); return clock }
	first := createLink(t, h, `{"url":"https://one.example"}`)
	second := createLink(t, h, `{"url":"https://two.example"}`)

	got := decode[[]link.Link](t, do(t, h, http.MethodGet, "/api/links", ""))
	if len(got) != 2 || got[0].Code != second.Code || got[1].Code != first.Code {
		t.Fatalf("list = %+v, want newest (%s) first", got, second.Code)
	}
	if got[0].ShortURL == "" {
		t.Fatal("short_url missing in list")
	}
}

func TestDeleteLink(t *testing.T) {
	_, h := newTestServer(t)
	l := createLink(t, h, `{"url":"https://example.com/bye"}`)

	rec := do(t, h, http.MethodDelete, "/api/links/"+l.Code, "")
	if rec.Code != http.StatusNoContent || rec.Body.Len() != 0 {
		t.Fatalf("DELETE = %d %q, want 204 with empty body", rec.Code, rec.Body)
	}
	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/" + l.Code},
		{http.MethodGet, "/api/links/" + l.Code},
		{http.MethodDelete, "/api/links/" + l.Code},
	} {
		if rec := do(t, h, tc.method, tc.path, ""); rec.Code != http.StatusNotFound {
			t.Errorf("%s %s after delete = %d, want 404", tc.method, tc.path, rec.Code)
		}
	}
}

// TestRoutePrecedence proves "GET /{code}" does not swallow the fixed routes.
func TestRoutePrecedence(t *testing.T) {
	_, h := newTestServer(t)
	tests := []struct {
		method, path string
		wantStatus   int
		wantBody     string
	}{
		{"GET", "/healthz", 200, `"ok"`},
		{"GET", "/readyz", 200, `"ready"`},
		{"GET", "/api/links", 200, `[`},
		{"GET", "/api", 404, `link not found`}, // one segment → redirect handler, reserved so never a link
		{"GET", "/api/links/xyz", 404, `link not found`},
		{"POST", "/healthz", 405, ``},
		{"GET", "/a/b", 404, ``}, // two segments: no route at all
	}
	for _, tt := range tests {
		t.Run(tt.method+" "+tt.path, func(t *testing.T) {
			rec := do(t, h, tt.method, tt.path, "")
			if rec.Code != tt.wantStatus || !strings.Contains(rec.Body.String(), tt.wantBody) {
				t.Fatalf("%s %s = %d %q, want %d containing %q", tt.method, tt.path, rec.Code, rec.Body, tt.wantStatus, tt.wantBody)
			}
		})
	}
}

func TestPanicRecovery(t *testing.T) {
	s, _ := newTestServer(t)
	h := s.logRequests(s.recoverPanics(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("boom")
	})))
	rec := do(t, h, http.MethodGet, "/anything", "")
	if rec.Code != http.StatusInternalServerError || decode[errorResponse](t, rec).Error != "internal error" {
		t.Fatalf("panic = %d %s, want 500 internal error", rec.Code, rec.Body)
	}
}

func TestStatusFor(t *testing.T) {
	tests := []struct {
		err  error
		want int
	}{
		{link.ErrInvalidURL, 400},
		{fmt.Errorf("%w: scheme", link.ErrInvalidURL), 400},
		{link.ErrInvalidCode, 400},
		{errBadJSON, 400},
		{link.ErrCodeTaken, 409},
		{link.ErrNotFound, 404},
		{fmt.Errorf("get: %w", link.ErrNotFound), 404},
		{errors.New("redis: connection refused"), 500},
	}
	for _, tt := range tests {
		if got := statusFor(tt.err); got != tt.want {
			t.Errorf("statusFor(%v) = %d, want %d", tt.err, got, tt.want)
		}
	}
}
