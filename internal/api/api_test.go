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
	"strings"
	"testing"

	"minibank/internal/store"
)

// HTTP tests run the real router + middleware against the in-memory store.

func newTestServer(t *testing.T) *Server {
	t.Helper()
	return New(store.NewMemory(), slog.New(slog.NewJSONHandler(io.Discard, nil)))
}

type response struct {
	status int
	header http.Header
	body   []byte
}

func (r response) decode(t *testing.T, v any) {
	t.Helper()
	if err := json.Unmarshal(r.body, v); err != nil {
		t.Fatalf("decode %q: %v", r.body, err)
	}
}

func do(t *testing.T, h http.Handler, method, path, body string) response {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return response{status: rec.Code, header: rec.Header(), body: rec.Body.Bytes()}
}

// expect checks status, the JSON content type and, for errors, the
// {"error": "..."} shape.
func expect(t *testing.T, r response, status int) {
	t.Helper()
	if r.status != status {
		t.Fatalf("status = %d, want %d (body %s)", r.status, status, r.body)
	}
	if ct := r.header.Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("Content-Type = %q, want application/json", ct)
	}
	if status >= 400 {
		var e map[string]string
		r.decode(t, &e)
		if e["error"] == "" {
			t.Fatalf("error response without \"error\" key: %s", r.body)
		}
	}
}

type account struct {
	ID      int64  `json:"id"`
	Owner   string `json:"owner"`
	Balance int64  `json:"balance"`
}

func createAccount(t *testing.T, h http.Handler, owner string) account {
	t.Helper()
	r := do(t, h, http.MethodPost, "/accounts", fmt.Sprintf(`{"owner":%q}`, owner))
	expect(t, r, http.StatusCreated)
	var a account
	r.decode(t, &a)
	return a
}

func TestHealthz(t *testing.T) {
	r := do(t, newTestServer(t), http.MethodGet, "/healthz", "")
	expect(t, r, http.StatusOK)
	if string(r.body) != "{\"status\":\"ok\"}\n" {
		t.Fatalf("body = %s", r.body)
	}
}

// downStore is a Store whose datastore is unreachable.
type downStore struct{ store.Store }

func (downStore) Ping(context.Context) error { return errors.New("connection refused") }

func TestReadyz(t *testing.T) {
	expect(t, do(t, newTestServer(t), http.MethodGet, "/readyz", ""), http.StatusOK)

	down := New(downStore{store.NewMemory()}, slog.New(slog.NewJSONHandler(io.Discard, nil)))
	r := do(t, down, http.MethodGet, "/readyz", "")
	if r.status != http.StatusServiceUnavailable || !strings.Contains(string(r.body), `"not ready"`) {
		t.Fatalf("readyz with DB down = %d %s, want 503 not ready", r.status, r.body)
	}
	// Liveness must stay green when only the database is down.
	expect(t, do(t, down, http.MethodGet, "/healthz", ""), http.StatusOK)
}

func TestCreateAccount(t *testing.T) {
	tests := []struct {
		name      string
		body      string
		status    int
		wantOwner string
	}{
		{"trims owner", `{"owner":"  Sara  "}`, http.StatusCreated, "Sara"},
		{"persian 4 runes / 8 bytes", `{"owner":"سارا"}`, http.StatusCreated, "سارا"},
		{"one rune", `{"owner":"a"}`, http.StatusBadRequest, ""},
		{"41 runes", `{"owner":"` + strings.Repeat("x", 41) + `"}`, http.StatusBadRequest, ""},
		{"whitespace only", `{"owner":"     "}`, http.StatusBadRequest, ""},
		{"invalid JSON", `{"owner":`, http.StatusBadRequest, ""},
		{"empty body", ``, http.StatusBadRequest, ""},
		{"owner wrong type", `{"owner":42}`, http.StatusBadRequest, ""},
		{"trailing data", `{"owner":"Sara"}{"owner":"Reza"}`, http.StatusBadRequest, ""},
	}
	h := newTestServer(t)
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := do(t, h, http.MethodPost, "/accounts", tt.body)
			expect(t, r, tt.status)
			if tt.status == http.StatusCreated {
				var a account
				r.decode(t, &a)
				if a.Owner != tt.wantOwner || a.Balance != 0 || a.ID <= 0 {
					t.Fatalf("account = %+v", a)
				}
			}
		})
	}
}

func TestGetAndListAccounts(t *testing.T) {
	h := newTestServer(t)

	r := do(t, h, http.MethodGet, "/accounts", "")
	expect(t, r, http.StatusOK)
	if strings.TrimSpace(string(r.body)) != "[]" {
		t.Fatalf("empty list = %s, want []", r.body)
	}

	a := createAccount(t, h, "Sara")
	b := createAccount(t, h, "Reza")
	var list []account
	r = do(t, h, http.MethodGet, "/accounts", "")
	expect(t, r, http.StatusOK)
	r.decode(t, &list)
	if len(list) != 2 || list[0].ID != a.ID || list[1].ID != b.ID {
		t.Fatalf("list = %+v", list)
	}

	tests := []struct {
		name   string
		path   string
		status int
	}{
		{"existing", fmt.Sprintf("/accounts/%d", a.ID), http.StatusOK},
		{"unknown", "/accounts/999999999999", http.StatusNotFound},
		{"not a number", "/accounts/abc", http.StatusBadRequest},
		{"zero", "/accounts/0", http.StatusBadRequest},
		{"negative", "/accounts/-3", http.StatusBadRequest},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			expect(t, do(t, h, http.MethodGet, tt.path, ""), tt.status)
		})
	}
}

func TestDepositAndWithdraw(t *testing.T) {
	h := newTestServer(t)
	a := createAccount(t, h, "Sara")
	base := fmt.Sprintf("/accounts/%d", a.ID)

	r := do(t, h, http.MethodPost, base+"/deposit", `{"amount":500}`)
	expect(t, r, http.StatusOK)
	var got account
	r.decode(t, &got)
	if got.Balance != 500 {
		t.Fatalf("balance after deposit = %d", got.Balance)
	}

	for _, body := range []string{`{"amount":0}`, `{"amount":-5}`, `{"amount":10.5}`,
		`{"amount":"100"}`, `{"amount":1000000001}`, `{}`} {
		t.Run("bad deposit "+body, func(t *testing.T) {
			expect(t, do(t, h, http.MethodPost, base+"/deposit", body), http.StatusBadRequest)
		})
	}
	expect(t, do(t, h, http.MethodPost, "/accounts/999999999999/deposit", `{"amount":5}`), http.StatusNotFound)

	r = do(t, h, http.MethodPost, base+"/withdraw", `{"amount":200}`)
	expect(t, r, http.StatusOK)
	r.decode(t, &got)
	if got.Balance != 300 {
		t.Fatalf("balance after withdraw = %d", got.Balance)
	}

	r = do(t, h, http.MethodPost, base+"/withdraw", `{"amount":10000}`)
	expect(t, r, http.StatusConflict)
	if !strings.Contains(string(r.body), `"insufficient funds"`) {
		t.Fatalf("409 body = %s", r.body)
	}
	do(t, h, http.MethodGet, base, "").decode(t, &got)
	if got.Balance != 300 {
		t.Fatalf("failed withdraw changed the balance to %d", got.Balance)
	}
}

func TestTransfer(t *testing.T) {
	h := newTestServer(t)
	a := createAccount(t, h, "Sara")
	b := createAccount(t, h, "Reza")
	expect(t, do(t, h, http.MethodPost, fmt.Sprintf("/accounts/%d/deposit", a.ID), `{"amount":1000}`), http.StatusOK)

	r := do(t, h, http.MethodPost, "/transfers", fmt.Sprintf(`{"from":%d,"to":%d,"amount":300}`, a.ID, b.ID))
	expect(t, r, http.StatusCreated)
	var tx map[string]any
	r.decode(t, &tx)
	if tx["type"] != "transfer" || tx["from"] != float64(a.ID) || tx["to"] != float64(b.ID) || tx["amount"] != float64(300) {
		t.Fatalf("transfer = %v", tx)
	}

	tests := []struct {
		name   string
		body   string
		status int
	}{
		{"same account", fmt.Sprintf(`{"from":%d,"to":%d,"amount":1}`, a.ID, a.ID), http.StatusBadRequest},
		{"bad amount", fmt.Sprintf(`{"from":%d,"to":%d,"amount":0}`, a.ID, b.ID), http.StatusBadRequest},
		{"bad JSON", `{"from":`, http.StatusBadRequest},
		{"unknown to", fmt.Sprintf(`{"from":%d,"to":999999999999,"amount":1}`, a.ID), http.StatusNotFound},
		{"insufficient", fmt.Sprintf(`{"from":%d,"to":%d,"amount":5000}`, b.ID, a.ID), http.StatusConflict},
		{"404 before 409", fmt.Sprintf(`{"from":%d,"to":999999999999,"amount":1000000000}`, b.ID), http.StatusNotFound},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			expect(t, do(t, h, http.MethodPost, "/transfers", tt.body), tt.status)
		})
	}
}

func TestTransactionsJSONShape(t *testing.T) {
	h := newTestServer(t)
	a := createAccount(t, h, "Sara")
	b := createAccount(t, h, "Reza")
	base := fmt.Sprintf("/accounts/%d", a.ID)

	r := do(t, h, http.MethodGet, base+"/transactions", "")
	expect(t, r, http.StatusOK)
	if strings.TrimSpace(string(r.body)) != "[]" {
		t.Fatalf("no transactions = %s, want []", r.body)
	}

	do(t, h, http.MethodPost, base+"/deposit", `{"amount":500}`)
	do(t, h, http.MethodPost, base+"/withdraw", `{"amount":200}`)
	do(t, h, http.MethodPost, "/transfers", fmt.Sprintf(`{"from":%d,"to":%d,"amount":50}`, a.ID, b.ID))

	var txs []map[string]any
	r = do(t, h, http.MethodGet, base+"/transactions", "")
	expect(t, r, http.StatusOK)
	r.decode(t, &txs)
	if len(txs) != 3 {
		t.Fatalf("got %d transactions: %s", len(txs), r.body)
	}
	if _, ok := txs[0]["from"]; ok || txs[0]["type"] != "deposit" {
		t.Fatalf("deposit must not have a from key: %v", txs[0])
	}
	if _, ok := txs[1]["to"]; ok || txs[1]["type"] != "withdraw" {
		t.Fatalf("withdraw must not have a to key: %v", txs[1])
	}

	r = do(t, h, http.MethodGet, fmt.Sprintf("/accounts/%d/transactions", b.ID), "")
	r.decode(t, &txs)
	if len(txs) != 1 || txs[0]["type"] != "transfer" {
		t.Fatalf("receiver history = %s", r.body)
	}
	expect(t, do(t, h, http.MethodGet, "/accounts/999999999999/transactions", ""), http.StatusNotFound)
	expect(t, do(t, h, http.MethodGet, "/accounts/abc/transactions", ""), http.StatusBadRequest)
}

func TestPanicRecovery(t *testing.T) {
	h := recoverPanics(slog.New(slog.NewJSONHandler(io.Discard, nil)),
		http.HandlerFunc(func(http.ResponseWriter, *http.Request) { panic("boom") }))
	r := do(t, h, http.MethodGet, "/", "")
	expect(t, r, http.StatusInternalServerError)
	if !strings.Contains(string(r.body), `"internal error"`) {
		t.Fatalf("body = %s", r.body)
	}
}
