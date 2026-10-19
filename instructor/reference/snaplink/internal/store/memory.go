package store

import (
	"context"
	"sort"
	"sync"
	"time"

	"snaplink/internal/link"
)

// Memory is an in-process Store. It is safe for concurrent use, but every
// replica has its own copy, so it must not be used with more than one replica.
//
// A plain Mutex (not RWMutex) on purpose: even "read" methods may delete an
// expired link (lazy TTL cleanup), so almost every call writes.
type Memory struct {
	mu    sync.Mutex
	links map[string]memEntry
	seq   uint64           // insertion counter, breaks created_at ties in List
	now   func() time.Time // injectable clock for TTL tests
}

type memEntry struct {
	link link.Link
	seq  uint64
}

// NewMemory returns an empty in-memory store.
func NewMemory() *Memory {
	return &Memory{links: make(map[string]memEntry), now: time.Now}
}

// lookup returns a live entry and removes it if it has expired.
// The caller must hold m.mu.
func (m *Memory) lookup(code string) (memEntry, bool) {
	e, ok := m.links[code]
	if !ok {
		return memEntry{}, false
	}
	if e.link.Expired(m.now()) {
		delete(m.links, code)
		return memEntry{}, false
	}
	return e, true
}

func (m *Memory) Create(_ context.Context, l link.Link) (link.Link, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	// Check and insert under the same lock: that is what makes the claim atomic.
	if _, ok := m.lookup(l.Code); ok {
		return link.Link{}, link.ErrCodeTaken
	}
	m.seq++
	m.links[l.Code] = memEntry{link: l, seq: m.seq}
	return l, nil
}

func (m *Memory) Get(_ context.Context, code string) (link.Link, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.lookup(code)
	if !ok {
		return link.Link{}, link.ErrNotFound
	}
	return e.link, nil
}

func (m *Memory) List(_ context.Context) ([]link.Link, error) {
	m.mu.Lock()
	entries := make([]memEntry, 0, len(m.links))
	for code := range m.links {
		if e, ok := m.lookup(code); ok { // deleting during range is allowed in Go
			entries = append(entries, e)
		}
	}
	m.mu.Unlock()

	sort.Slice(entries, func(i, j int) bool {
		a, b := entries[i], entries[j]
		if !a.link.CreatedAt.Equal(b.link.CreatedAt) {
			return a.link.CreatedAt.After(b.link.CreatedAt)
		}
		return a.seq > b.seq
	})
	out := make([]link.Link, len(entries))
	for i, e := range entries {
		out[i] = e.link
	}
	return out, nil
}

func (m *Memory) Delete(_ context.Context, code string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.lookup(code); !ok {
		return link.ErrNotFound
	}
	delete(m.links, code)
	return nil
}

func (m *Memory) Hit(_ context.Context, code string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.lookup(code)
	if !ok {
		return "", link.ErrNotFound
	}
	// Read-modify-write is safe here only because we hold the lock.
	e.link.Clicks++
	m.links[code] = e
	return e.link.URL, nil
}

func (m *Memory) Ping(context.Context) error { return nil }
