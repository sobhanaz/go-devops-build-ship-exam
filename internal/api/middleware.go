package api

import (
	"fmt"
	"net/http"
	"runtime/debug"
	"time"
)

// statusRecorder remembers the status code written by the inner handler.
type statusRecorder struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (r *statusRecorder) WriteHeader(code int) {
	if !r.wroteHeader {
		r.status = code
		r.wroteHeader = true
	}
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Write(b []byte) (int, error) {
	r.wroteHeader = true // implicit 200
	return r.ResponseWriter.Write(b)
}

// Unwrap lets http.ResponseController reach the real writer.
func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }

// logRequests writes one JSON log line per request.
func (s *Server) logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		s.log.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rec.status,
			"duration_ms", float64(time.Since(start).Microseconds())/1000,
		)
	})
}

// recoverPanics turns a panic in a handler into a logged 500 JSON response
// instead of a dropped connection.
func (s *Server) recoverPanics(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			v := recover()
			if v == nil {
				return
			}
			if v == http.ErrAbortHandler { // deliberate abort: let net/http handle it
				panic(v)
			}
			s.log.Error("panic recovered",
				"method", r.Method, "path", r.URL.Path,
				"panic", fmt.Sprint(v), "stack", string(debug.Stack()))
			writeJSON(w, http.StatusInternalServerError, errorResponse{Error: "internal error"})
		}()
		next.ServeHTTP(w, r)
	})
}
