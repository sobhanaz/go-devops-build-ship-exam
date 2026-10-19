package api

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"runtime/debug"
	"time"
)

// statusRecorder remembers the status code a handler wrote so middleware can
// log it and count it.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func newStatusRecorder(w http.ResponseWriter) *statusRecorder {
	return &statusRecorder{ResponseWriter: w, status: http.StatusOK}
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

// Unwrap lets http.ResponseController reach the real ResponseWriter.
func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }

// logRequests writes one JSON log line per request.
func logRequests(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := newStatusRecorder(w)
		next.ServeHTTP(rec, r)
		logger.LogAttrs(r.Context(), slog.LevelInfo, "request",
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.Int("status", rec.status),
			slog.Float64("duration_ms", float64(time.Since(start).Microseconds())/1000),
		)
	})
}

// recoverPanics turns a panic in a handler into a logged 500 instead of a
// dropped connection, and keeps the server alive.
func recoverPanics(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			v := recover()
			if v == nil {
				return
			}
			// http.ErrAbortHandler is net/http's way to abort a response on
			// purpose; re-panic so the server handles it as designed.
			if err, ok := v.(error); ok && errors.Is(err, http.ErrAbortHandler) {
				panic(v)
			}
			logger.ErrorContext(r.Context(), "panic recovered",
				"panic", fmt.Sprint(v), "method", r.Method, "path", r.URL.Path,
				"stack", string(debug.Stack()))
			writeError(w, http.StatusInternalServerError, "internal error")
		}()
		next.ServeHTTP(w, r)
	})
}
