package store

import "testing"

func TestMemoryStore(t *testing.T) {
	runStoreContract(t, NewMemory())
}

func TestMemoryStoreConcurrency(t *testing.T) {
	runConcurrencyStorm(t, NewMemory())
}

func TestMemoryIDsStartAtOneAndIncrease(t *testing.T) {
	st := NewMemory()
	for want := int64(1); want <= 3; want++ {
		acc := mustAccount(t, st, "Owner", 0)
		if acc.ID != want {
			t.Fatalf("id = %d, want %d", acc.ID, want)
		}
	}
}
