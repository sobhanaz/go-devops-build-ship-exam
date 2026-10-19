// Package api is the HTTP layer: routes, handlers, JSON helpers, the single
// error→status mapping and the middleware. It only talks to store.Store.
package api

import (
	"log/slog"
	"net/http"
	"strings"
	"time"

	"snaplink/internal/store"
)

// Server holds the dependencies of the HTTP handlers.
type Server struct {
	store   store.Store
	baseURL string
	log     *slog.Logger
	metrics *metrics
	now     func() time.Time
}

// New builds a Server. baseURL is used for short_url (trailing slash removed).
func New(st store.Store, baseURL string, logger *slog.Logger) *Server {
	return &Server{
		store:   st,
		baseURL: strings.TrimRight(baseURL, "/"),
		log:     logger,
		metrics: newMetrics(),
		now:     time.Now,
	}
}

// Handler returns all routes wrapped in the middleware chain.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	// Go 1.22 ServeMux patterns. "GET /{code}" matches every one-segment path,
	// but when two patterns match, ServeMux picks the MORE SPECIFIC one, so the
	// literal /healthz and /readyz win. /api/links/... has more segments and
	// can never reach the redirect handler. TestRoutePrecedence pins this down.
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /readyz", s.readyz)
	mux.Handle("GET /metrics", s.metrics.handler())
	mux.HandleFunc("POST /api/links", s.createLink)
	mux.HandleFunc("GET /api/links", s.listLinks)
	mux.HandleFunc("GET /api/links/{code}", s.getLink)
	mux.HandleFunc("DELETE /api/links/{code}", s.deleteLink)
	mux.HandleFunc("GET /{code}", s.redirect)

	// Outermost first: logger and metrics both see the 500 that the
	// recoverer writes after a panic.
	return s.logRequests(s.instrument(mux, s.recoverPanics(mux)))
}
