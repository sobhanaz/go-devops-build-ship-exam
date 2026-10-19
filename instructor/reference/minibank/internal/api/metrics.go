package api

import (
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"minibank/internal/bank"
)

// metrics holds the Prometheus collectors (bonus B1).
//
// Each Server gets its own registry instead of the global default one, so
// tests can create many servers without "duplicate metrics collector
// registration" panics.
type metrics struct {
	registry  *prometheus.Registry
	requests  *prometheus.CounterVec
	duration  *prometheus.HistogramVec
	transfers *prometheus.CounterVec
}

func newMetrics() *metrics {
	m := &metrics{
		registry: prometheus.NewRegistry(),
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "http_requests_total",
			Help: "HTTP requests by method, route pattern and status code.",
		}, []string{"method", "path", "status"}),
		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "HTTP request latency by method and route pattern.",
			Buckets: prometheus.DefBuckets,
		}, []string{"method", "path"}),
		transfers: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "minibank_transfers_total",
			Help: "Transfer attempts by result (ok, insufficient_funds, error).",
		}, []string{"result"}),
	}
	m.registry.MustRegister(m.requests, m.duration, m.transfers,
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}))
	// Pre-create the series so dashboards show 0 instead of "no data".
	for _, result := range []string{"ok", "insufficient_funds", "error"} {
		m.transfers.WithLabelValues(result)
	}
	return m
}

func (m *metrics) handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{})
}

// instrument counts and times every request. The path label is the ROUTE
// PATTERN ("/accounts/{id}"), never the raw URL: one label value per account
// id would create unbounded time series and eventually kill Prometheus.
//
// route resolves the pattern with ServeMux.Handler, which works on Go 1.22
// (http.Request.Pattern only exists from Go 1.23).
func (m *metrics) instrument(route func(*http.Request) string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := newStatusRecorder(w)
		next.ServeHTTP(rec, r)
		path := route(r)
		m.requests.WithLabelValues(r.Method, path, strconv.Itoa(rec.status)).Inc()
		m.duration.WithLabelValues(r.Method, path).Observe(time.Since(start).Seconds())
	})
}

func (m *metrics) observeTransfer(err error) {
	result := "ok"
	switch {
	case err == nil:
	case errors.Is(err, bank.ErrInsufficientFunds):
		result = "insufficient_funds"
	default:
		result = "error"
	}
	m.transfers.WithLabelValues(result).Inc()
}

// routeLabel turns a mux pattern like "GET /accounts/{id}" into
// "/accounts/{id}". Requests that match no route share one label value.
func routeLabel(mux *http.ServeMux) func(*http.Request) string {
	return func(r *http.Request) string {
		_, pattern := mux.Handler(r)
		if pattern == "" {
			return "unmatched"
		}
		if _, path, ok := strings.Cut(pattern, " "); ok {
			return path
		}
		return pattern
	}
}
