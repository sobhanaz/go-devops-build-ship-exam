package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	"minibank/internal/bank"
)

const maxBodyBytes = 1 << 20 // 1 MB

var (
	errBadJSON      = errors.New("invalid JSON body")
	errBodyTooLarge = errors.New("request body larger than 1 MB")
)

// writeJSON writes v as JSON with the given status. Every response of the
// app's handlers goes through here (or writeError), so the Content-Type is
// always application/json.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	// An encode error here means the client went away; nothing useful to do.
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// decodeJSON reads exactly one JSON object of at most 1 MB into dst.
// Wrong types are errors too: {"amount":10.5} and {"amount":"100"} cannot be
// decoded into an int64 and therefore become 400.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil {
		var tooBig *http.MaxBytesError
		var typeErr *json.UnmarshalTypeError
		switch {
		case errors.As(err, &tooBig):
			return errBodyTooLarge
		case errors.Is(err, io.EOF):
			return fmt.Errorf("%w: body is empty", errBadJSON)
		case errors.As(err, &typeErr):
			return fmt.Errorf("%w: field %q has the wrong type", errBadJSON, typeErr.Field)
		default:
			return errBadJSON
		}
	}
	// Reject trailing data such as {"amount":1}{"amount":2}.
	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return fmt.Errorf("%w: body must contain a single JSON object", errBadJSON)
	}
	return nil
}

// statusFor is the ONE place where errors become HTTP status codes.
// Anything unknown is a 500 (and is logged by the caller).
func statusFor(err error) int {
	switch {
	case errors.Is(err, errBadJSON),
		errors.Is(err, bank.ErrInvalidOwner),
		errors.Is(err, bank.ErrInvalidAmount),
		errors.Is(err, bank.ErrInvalidID),
		errors.Is(err, bank.ErrSameAccount):
		return http.StatusBadRequest
	case errors.Is(err, errBodyTooLarge):
		return http.StatusRequestEntityTooLarge
	case errors.Is(err, bank.ErrAccountNotFound):
		return http.StatusNotFound
	case errors.Is(err, bank.ErrInsufficientFunds):
		return http.StatusConflict
	default:
		return http.StatusInternalServerError
	}
}
