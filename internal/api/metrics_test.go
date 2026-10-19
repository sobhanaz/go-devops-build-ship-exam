package api

import (
	"net/http"
	"strings"
	"testing"
)

func TestMetrics(t *testing.T) {
	_, h := newTestServer(t)
	l := createLink(t, h, `{"url":"https://example.com/metrics"}`)
	do(t, h, http.MethodGet, "/"+l.Code, "")
	do(t, h, http.MethodGet, "/no-such-code", "")

	rec := do(t, h, http.MethodGet, "/metrics", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /metrics = %d", rec.Code)
	}
	body := rec.Body.String()
	for _, want := range []string{
		"# TYPE http_requests_total counter",
		`http_requests_total{method="GET",path="/{code}",status="302"} 1`,
		`http_requests_total{method="GET",path="/{code}",status="404"} 1`,
		`http_requests_total{method="POST",path="/api/links",status="201"} 1`,
		"http_request_duration_seconds_bucket",
		"snaplink_redirects_total 1",
		"snaplink_links_created_total 1",
	} {
		if !strings.Contains(body, want) {
			t.Errorf("metrics output is missing %q", want)
		}
	}
	// The raw code must never become a label value (cardinality explosion).
	if strings.Contains(body, l.Code) {
		t.Errorf("metrics contain the raw code %q", l.Code)
	}
}
