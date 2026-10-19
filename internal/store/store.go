// Package store defines how links are persisted and provides two
// implementations: Memory (tests, quick local runs) and Redis (compose, k8s).
package store

import (
	"context"

	"snaplink/internal/link"
)

// Store is the persistence port used by the HTTP layer. Both implementations
// must give the same guarantees; the shared contract tests check that.
type Store interface {
	// Create stores l under l.Code. ErrCodeTaken if the code already exists.
	Create(ctx context.Context, l link.Link) (link.Link, error)
	// Get returns the link with its current click count. ErrNotFound.
	Get(ctx context.Context, code string) (link.Link, error)
	// List returns all links, newest first. Never nil.
	List(ctx context.Context) ([]link.Link, error)
	// Delete removes the link and its index entry. ErrNotFound.
	Delete(ctx context.Context, code string) error
	// Hit atomically increments clicks and returns the target url. ErrNotFound.
	Hit(ctx context.Context, code string) (string, error)
	// Ping checks the backing datastore (used by /readyz only).
	Ping(ctx context.Context) error
}
