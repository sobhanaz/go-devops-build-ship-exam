package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	"snaplink/internal/link"
)

const maxBodyBytes = 1 << 20 // 1 MB

// errBadJSON is an API-level error: the body is not the JSON we expect.
var errBadJSON = errors.New("invalid JSON body")

type errorResponse struct {
	Error string `json:"error"`
}

// statusFor is the ONE place that maps errors to HTTP status codes.
func statusFor(err error) int {
	switch {
	case errors.Is(err, errBadJSON),
		errors.Is(err, link.ErrInvalidURL),
		errors.Is(err, link.ErrInvalidCode):
		return http.StatusBadRequest
	case errors.Is(err, link.ErrCodeTaken):
		return http.StatusConflict
	case errors.Is(err, link.ErrNotFound):
		return http.StatusNotFound
	default:
		return http.StatusInternalServerError
	}
}

// writeError writes {"error": "..."} with the mapped status. Unknown errors
// are logged and hidden behind "internal error" so no internals leak.
func (s *Server) writeError(w http.ResponseWriter, r *http.Request, err error) {
	status := statusFor(err)
	msg := err.Error()
	if status == http.StatusInternalServerError {
		s.log.Error("request failed", "method", r.Method, "path", r.URL.Path, "err", err)
		msg = "internal error"
	}
	writeJSON(w, status, errorResponse{Error: msg})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false) // keep "&" in URLs readable
	_ = enc.Encode(v)        // the client is gone if this fails; nothing to do
}

// decodeJSON reads exactly one JSON value (max 1 MB) into dst.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			return fmt.Errorf("%w: body larger than 1 MB", errBadJSON)
		}
		return fmt.Errorf("%w: %v", errBadJSON, err)
	}
	// Reject trailing garbage such as `{"url":"..."} xyz`.
	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return fmt.Errorf("%w: unexpected data after the JSON object", errBadJSON)
	}
	return nil
}
