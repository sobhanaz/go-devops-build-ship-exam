package api

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// metrics uses its own registry instead of the global default one, so every
// Server (one per test, for example) can register the same names safely.
type metrics struct {
	registry     *prometheus.Registry
	requests     *prometheus.CounterVec
	duration     *prometheus.HistogramVec
	redirects    prometheus.Counter
	linksCreated prometheus.Counter
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
		redirects: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "snaplink_redirects_total",
			Help: "Successful redirects, i.e. counted clicks.",
		}),
		linksCreated: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "snaplink_links_created_total",
			Help: "Links created.",
		}),
	}
	m.registry.MustRegister(
		m.requests, m.duration, m.redirects, m.linksCreated,
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	)
	return m
}

func (m *metrics) handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{})
}

// instrument counts requests and observes latency per ROUTE PATTERN. The raw
// path is not a safe label: every short code would create new time series
// (unbounded cardinality) until Prometheus runs out of memory.
func (s *Server) instrument(mux *http.ServeMux, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)

		path := routeLabel(mux, r)
		s.metrics.requests.WithLabelValues(r.Method, path, strconv.Itoa(rec.status)).Inc()
		s.metrics.duration.WithLabelValues(r.Method, path).Observe(time.Since(start).Seconds())
	})
}

// routeLabel returns the matched pattern without its method, e.g. "/{code}".
// (Go 1.23+ has r.Pattern; mux.Handler also works on Go 1.22.)
func routeLabel(mux *http.ServeMux, r *http.Request) string {
	_, pattern := mux.Handler(r)
	if pattern == "" {
		return "unmatched"
	}
	if _, path, ok := strings.Cut(pattern, " "); ok {
		return path
	}
	return pattern
}
