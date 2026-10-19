package store

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

// TestRedisContract is an integration test. It is SKIPPED unless
// SNAPLINK_TEST_REDIS_ADDR is set, so `go test ./...` passes without Redis:
//
//	SNAPLINK_TEST_REDIS_ADDR=localhost:6379 SNAPLINK_TEST_REDIS_PASSWORD=secret go test ./internal/store/
func TestRedisContract(t *testing.T) {
	addr := os.Getenv("SNAPLINK_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("SNAPLINK_TEST_REDIS_ADDR not set; skipping Redis integration test")
	}
	st := NewRedis(redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: os.Getenv("SNAPLINK_TEST_REDIS_PASSWORD"),
	}))
	t.Cleanup(func() { _ = st.Close() })

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := st.Ping(ctx); err != nil {
		t.Fatalf("cannot reach Redis at %s: %v", addr, err)
	}
	runContract(t, st)
}
