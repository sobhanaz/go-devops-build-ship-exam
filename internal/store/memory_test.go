package store

import (
	"context"
	"testing"
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
