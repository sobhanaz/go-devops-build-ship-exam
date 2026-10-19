package store

import (
	"context"
	"errors"
	"testing"
	"time"

	"snaplink/internal/link"
)

func TestMemoryContract(t *testing.T) {
	runContract(t, NewMemory())
}

func TestMemoryListEmptyIsNotNil(t *testing.T) {
	got, err := NewMemory().List(context.Background())
	if err != nil || got == nil || len(got) != 0 {
		t.Fatalf("List on empty store = %#v, %v; want empty non-nil slice", got, err)
	}
}

func TestMemoryTTLWithFakeClock(t *testing.T) {
	m := NewMemory()
	now := time.Date(2026, 10, 20, 9, 0, 0, 0, time.UTC)
	m.now = func() time.Time { return now }

	exp := now.Add(2 * time.Second)
	if _, err := m.Create(context.Background(), link.Link{Code: "ttl", URL: "https://x.dev", CreatedAt: now, ExpiresAt: &exp}); err != nil {
		t.Fatal(err)
	}
	now = now.Add(1999 * time.Millisecond)
	if _, err := m.Hit(context.Background(), "ttl"); err != nil {
		t.Fatalf("1.999s after create: %v, want still alive", err)
	}
	now = now.Add(time.Millisecond) // exactly expires_at: expired
	if _, err := m.Hit(context.Background(), "ttl"); !errors.Is(err, link.ErrNotFound) {
		t.Fatalf("at expires_at: err = %v, want ErrNotFound", err)
	}
	if len(m.links) != 0 {
		t.Fatalf("expired entry not cleaned up: %d entries left", len(m.links))
	}
}
