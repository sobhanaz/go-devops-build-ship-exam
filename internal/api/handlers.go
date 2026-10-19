package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"snaplink/internal/link"
)

// maxCodeAttempts bounds the retry loop for random-code collisions.
const maxCodeAttempts = 5

// healthz is the LIVENESS probe: "is the process alive and serving HTTP?".
// It must never touch Redis: if it did, a Redis outage would make Kubernetes
// restart every (perfectly healthy) app pod, which fixes nothing.
func (s *Server) healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// readyz is the READINESS probe: "can I serve real traffic right now?".
// 503 only removes the pod from the Service endpoints until Redis is back.
func (s *Server) readyz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.store.Ping(ctx); err != nil {
		s.log.Warn("readiness check failed", "err", err)
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "not ready"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

type createRequest struct {
	URL        string `json:"url"`
	Code       string `json:"code"`
	TTLSeconds *int64 `json:"ttl_seconds"` // pointer: absent ≠ 0
}

func (s *Server) createLink(w http.ResponseWriter, r *http.Request) {
	var req createRequest
	if err := decodeJSON(w, r, &req); err != nil {
		// 1.5 or "10" for ttl_seconds fail inside json decoding; give them
		// the TTL error message rather than a generic JSON one.
		var typeErr *json.UnmarshalTypeError
		if errors.As(err, &typeErr) && typeErr.Field == "ttl_seconds" {
			err = fmt.Errorf("%w: must be a whole number of seconds", link.ErrInvalidTTL)
		}
		s.writeError(w, r, err)
		return
	}
	// Every 400 check happens before we touch the store, so a bad request
	// with a taken code is still a 400 (contract: 400 before 409).
	if err := link.ValidateURL(req.URL); err != nil {
		s.writeError(w, r, err)
		return
	}
	if req.Code != "" {
		if err := link.ValidateCode(req.Code); err != nil {
			s.writeError(w, r, err)
			return
		}
	}
	if req.TTLSeconds != nil {
		if err := link.ValidateTTL(*req.TTLSeconds); err != nil {
			s.writeError(w, r, err)
			return
		}
	}

	l := link.Link{
		URL: req.URL,
		// Millisecond precision on purpose: the Redis ZSET score is unix ms,
		// so equal scores always mean equal created_at (stable ordering).
		CreatedAt: s.now().UTC().Truncate(time.Millisecond),
	}
	if req.TTLSeconds != nil {
		exp := l.CreatedAt.Add(time.Duration(*req.TTLSeconds) * time.Second)
		l.ExpiresAt = &exp
	}
	created, err := s.create(r.Context(), l, req.Code)
	if err != nil {
		s.writeError(w, r, err)
		return
	}
	s.metrics.linksCreated.Inc()
	writeJSON(w, http.StatusCreated, s.present(created))
}

// create stores l under the custom code, or under a fresh random code.
// A random code may collide with an existing one (rare): retry. A taken
// custom code is the client's problem: ErrCodeTaken → 409.
func (s *Server) create(ctx context.Context, l link.Link, custom string) (link.Link, error) {
	if custom != "" {
		l.Code = custom
		return s.store.Create(ctx, l)
	}
	for i := 0; i < maxCodeAttempts; i++ {
		code, err := link.NewCode()
		if err != nil {
			return link.Link{}, err
		}
		l.Code = code
		created, err := s.store.Create(ctx, l)
		if !errors.Is(err, link.ErrCodeTaken) {
			return created, err
		}
	}
	return link.Link{}, errors.New("no free code after several attempts")
}

func (s *Server) listLinks(w http.ResponseWriter, r *http.Request) {
	links, err := s.store.List(r.Context())
	if err != nil {
		s.writeError(w, r, err)
		return
	}
	out := make([]link.Link, 0, len(links)) // never encode null
	for _, l := range links {
		out = append(out, s.present(l))
	}
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) getLink(w http.ResponseWriter, r *http.Request) {
	l, err := s.store.Get(r.Context(), r.PathValue("code"))
	if err != nil {
		s.writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, s.present(l))
}

func (s *Server) deleteLink(w http.ResponseWriter, r *http.Request) {
	if err := s.store.Delete(r.Context(), r.PathValue("code")); err != nil {
		s.writeError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) redirect(w http.ResponseWriter, r *http.Request) {
	target, err := s.store.Hit(r.Context(), r.PathValue("code"))
	if err != nil {
		s.writeError(w, r, err)
		return
	}
	// no-store: browsers and proxies must come back every time, otherwise a
	// repeat visit would be served from cache and never counted.
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Location", target)
	w.WriteHeader(http.StatusFound)
	s.metrics.redirects.Inc()
}

// present adds the fields that are derived, not stored.
func (s *Server) present(l link.Link) link.Link {
	l.ShortURL = s.baseURL + "/" + l.Code
	return l
}
