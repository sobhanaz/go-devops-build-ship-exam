// Package api is the HTTP layer of MiniBank: routes, handlers, JSON helpers,
// the error→status mapping and middleware. It uses only net/http with the
// Go 1.22 ServeMux patterns ("GET /accounts/{id}").
package api

import (
	"log/slog"
	"net/http"

	"minibank/internal/store"
)

// Server is the MiniBank HTTP API. It implements http.Handler.
type Server struct {
	store   store.Store
	logger  *slog.Logger
	mux     *http.ServeMux
	handler http.Handler
}

// New builds the router and the middleware chain around st.
func New(st store.Store, logger *slog.Logger) *Server {
	s := &Server{
		store:  st,
		logger: logger,
		mux:    http.NewServeMux(),
	}
	s.routes()

	// Outermost first: the request log sees the final status, including the
	// 500 written by recoverPanics.
	var h http.Handler = s.mux
	h = recoverPanics(logger, h)
	h = logRequests(logger, h)
	s.handler = h
	return s
}

func (s *Server) routes() {
	s.mux.HandleFunc("GET /healthz", s.handleHealthz)
	s.mux.HandleFunc("GET /readyz", s.handleReadyz)

	s.mux.HandleFunc("POST /accounts", s.handleCreateAccount)
	s.mux.HandleFunc("GET /accounts", s.handleListAccounts)
	s.mux.HandleFunc("GET /accounts/{id}", s.handleGetAccount)
	s.mux.HandleFunc("POST /accounts/{id}/deposit", s.handleDeposit)
	s.mux.HandleFunc("POST /accounts/{id}/withdraw", s.handleWithdraw)
	s.mux.HandleFunc("GET /accounts/{id}/transactions", s.handleListTransactions)
	s.mux.HandleFunc("POST /transfers", s.handleTransfer)
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.handler.ServeHTTP(w, r)
}
