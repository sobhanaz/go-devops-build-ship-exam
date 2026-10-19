package api

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"minibank/internal/bank"
)

// readyTimeout bounds the datastore ping of /readyz. Keep it below the
// Kubernetes readinessProbe timeoutSeconds.
const readyTimeout = 2 * time.Second

// handleHealthz is the liveness check: "is this process alive?". It must
// NOT touch the database. If it did, a database outage would make Kubernetes
// restart every healthy app pod, which fixes nothing.
func (s *Server) handleHealthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// handleReadyz is the readiness check: "can this pod serve traffic right
// now?". When the database is down the pod is taken out of the Service
// endpoints (no traffic) but not restarted.
func (s *Server) handleReadyz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), readyTimeout)
	defer cancel()
	if err := s.store.Ping(ctx); err != nil {
		s.logger.WarnContext(ctx, "readiness check failed", "error", err)
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "not ready"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

func (s *Server) handleCreateAccount(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Owner string `json:"owner"`
	}
	if err := decodeJSON(w, r, &req); err != nil {
		s.fail(w, r, err)
		return
	}
	acc, err := s.store.CreateAccount(r.Context(), req.Owner)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	w.Header().Set("Location", fmt.Sprintf("/accounts/%d", acc.ID))
	writeJSON(w, http.StatusCreated, acc)
}

func (s *Server) handleListAccounts(w http.ResponseWriter, r *http.Request) {
	accs, err := s.store.ListAccounts(r.Context())
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, accs)
}

func (s *Server) handleGetAccount(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	acc, err := s.store.GetAccount(r.Context(), id)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, acc)
}

func (s *Server) handleDeposit(w http.ResponseWriter, r *http.Request) {
	s.changeBalance(w, r, s.store.Deposit)
}

func (s *Server) handleWithdraw(w http.ResponseWriter, r *http.Request) {
	s.changeBalance(w, r, s.store.Withdraw)
}

// changeBalance is the shared body of deposit and withdraw.
func (s *Server) changeBalance(w http.ResponseWriter, r *http.Request,
	op func(ctx context.Context, id, amount int64) (bank.Account, error)) {
	id, err := pathID(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	var req struct {
		Amount int64 `json:"amount"` // missing → 0 → ErrInvalidAmount
	}
	if err := decodeJSON(w, r, &req); err != nil {
		s.fail(w, r, err)
		return
	}
	acc, err := op(r.Context(), id, req.Amount)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, acc)
}

func (s *Server) handleTransfer(w http.ResponseWriter, r *http.Request) {
	var req struct {
		From   int64 `json:"from"`
		To     int64 `json:"to"`
		Amount int64 `json:"amount"`
	}
	if err := decodeJSON(w, r, &req); err != nil {
		s.metrics.observeTransfer(err)
		s.fail(w, r, err)
		return
	}
	tx, err := s.store.Transfer(r.Context(), req.From, req.To, req.Amount)
	s.metrics.observeTransfer(err)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, tx)
}

func (s *Server) handleListTransactions(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	txs, err := s.store.ListTransactions(r.Context(), id)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, txs)
}

// fail writes the error response for err. Internal errors are logged with
// their detail but the client only sees "internal error".
func (s *Server) fail(w http.ResponseWriter, r *http.Request, err error) {
	status := statusFor(err)
	msg := err.Error()
	if status == http.StatusInternalServerError {
		s.logger.ErrorContext(r.Context(), "request failed",
			"method", r.Method, "path", r.URL.Path, "error", err)
		msg = "internal error"
	}
	writeError(w, status, msg)
}

// pathID parses {id}. "abc", "0" and "-3" are all 400.
func pathID(r *http.Request) (int64, error) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil || id <= 0 {
		return 0, bank.ErrInvalidID
	}
	return id, nil
}
