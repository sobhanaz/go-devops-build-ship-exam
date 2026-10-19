package store

import (
	"os"
	"testing"
	"time"
)

// Integration tests against a real PostgreSQL. They are skipped unless
// MINIBANK_TEST_DATABASE_URL is set, so `go test -race ./...` passes on a
// laptop or CI runner without a database:
//
//	MINIBANK_TEST_DATABASE_URL='postgres://minibank:minibank@localhost:5432/minibank?sslmode=disable' \
//	  go test -race -count=1 ./internal/store/
//
// The tests only add rows; they work on a database that already has data.
func newTestPostgres(t *testing.T) *Postgres {
	t.Helper()
	url := os.Getenv("MINIBANK_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("MINIBANK_TEST_DATABASE_URL not set; skipping Postgres integration test")
	}
	pg, err := NewPostgres(ctx, url)
	if err != nil {
		t.Fatalf("NewPostgres: %v", err)
	}
	t.Cleanup(pg.Close)
	return pg
}

func TestPostgresStore(t *testing.T) {
	runStoreContract(t, newTestPostgres(t))
}

func TestPostgresStoreConcurrency(t *testing.T) {
	runConcurrencyStorm(t, newTestPostgres(t))
}

func TestPostgresMigrateIsIdempotent(t *testing.T) {
	pg := newTestPostgres(t)
	// Startup runs migrate on every pod start; running it again must be a no-op.
	if err := pg.migrate(ctx); err != nil {
		t.Fatalf("second migrate: %v", err)
	}
}

func TestPostgresTimestampsAreUTC(t *testing.T) {
	pg := newTestPostgres(t)
	acc := mustAccount(t, pg, "Clock", 0)
	if acc.CreatedAt.Location() != time.UTC {
		t.Fatalf("created_at location = %v, want UTC", acc.CreatedAt.Location())
	}
}
