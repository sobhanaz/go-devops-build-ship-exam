package store

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"slices"
	"sync"
	"sync/atomic"
	"testing"

	"minibank/internal/bank"
)

// The behaviour tests below are written once against the Store interface and
// run for every implementation (memory always, Postgres when a test database
// is configured). They never assume an empty store or ids starting at 1.

var ctx = context.Background()

func mustAccount(t *testing.T, st Store, owner string, balance int64) bank.Account {
	t.Helper()
	acc, err := st.CreateAccount(ctx, owner)
	if err != nil {
		t.Fatalf("CreateAccount(%q): %v", owner, err)
	}
	if balance > 0 {
		if acc, err = st.Deposit(ctx, acc.ID, balance); err != nil {
			t.Fatalf("Deposit: %v", err)
		}
	}
	return acc
}

func mustBalance(t *testing.T, st Store, id, want int64) {
	t.Helper()
	acc, err := st.GetAccount(ctx, id)
	if err != nil {
		t.Fatalf("GetAccount(%d): %v", id, err)
	}
	if acc.Balance != want {
		t.Fatalf("account %d balance = %d, want %d", id, acc.Balance, want)
	}
}

// unknownID returns an id that does not exist in st.
func unknownID(t *testing.T, st Store) int64 {
	t.Helper()
	accs, err := st.ListAccounts(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var maxID int64
	for _, a := range accs {
		maxID = max(maxID, a.ID)
	}
	return maxID + 1_000_000
}

func runStoreContract(t *testing.T, st Store) {
	t.Run("create get list", func(t *testing.T) {
		a := mustAccount(t, st, "  Sara  ", 0)
		b := mustAccount(t, st, "سارا", 0)
		if a.Owner != "Sara" || a.Balance != 0 || a.ID <= 0 || a.CreatedAt.IsZero() {
			t.Fatalf("unexpected account %+v", a)
		}
		if b.ID <= a.ID {
			t.Fatalf("ids must increase: %d then %d", a.ID, b.ID)
		}
		got, err := st.GetAccount(ctx, a.ID)
		if err != nil || got.ID != a.ID || got.Owner != a.Owner {
			t.Fatalf("GetAccount = %+v, %v", got, err)
		}
		list, err := st.ListAccounts(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if !slices.IsSortedFunc(list, func(x, y bank.Account) int { return cmp.Compare(x.ID, y.ID) }) {
			t.Fatal("ListAccounts must be sorted by id")
		}
		ids := make([]int64, 0, len(list))
		for _, acc := range list {
			ids = append(ids, acc.ID)
		}
		if !slices.Contains(ids, a.ID) || !slices.Contains(ids, b.ID) {
			t.Fatalf("ListAccounts misses %d or %d", a.ID, b.ID)
		}
	})

	t.Run("deposit withdraw transfer and history", func(t *testing.T) {
		a := mustAccount(t, st, "Alice", 0)
		b := mustAccount(t, st, "Bob", 0)
		if acc, err := st.Deposit(ctx, a.ID, 500); err != nil || acc.Balance != 500 {
			t.Fatalf("Deposit = %+v, %v", acc, err)
		}
		if acc, err := st.Withdraw(ctx, a.ID, 200); err != nil || acc.Balance != 300 {
			t.Fatalf("Withdraw = %+v, %v", acc, err)
		}
		tr, err := st.Transfer(ctx, a.ID, b.ID, 100)
		if err != nil {
			t.Fatalf("Transfer: %v", err)
		}
		if tr.Type != bank.TxTransfer || tr.From != a.ID || tr.To != b.ID || tr.Amount != 100 || tr.ID <= 0 {
			t.Fatalf("unexpected transfer %+v", tr)
		}
		mustBalance(t, st, a.ID, 200)
		mustBalance(t, st, b.ID, 100)

		hist, err := st.ListTransactions(ctx, a.ID)
		if err != nil {
			t.Fatal(err)
		}
		wantTypes := []bank.TxType{bank.TxDeposit, bank.TxWithdraw, bank.TxTransfer}
		if len(hist) != len(wantTypes) {
			t.Fatalf("history of %d has %d entries, want %d: %+v", a.ID, len(hist), len(wantTypes), hist)
		}
		for i, tx := range hist {
			if tx.Type != wantTypes[i] {
				t.Fatalf("entry %d type = %s, want %s", i, tx.Type, wantTypes[i])
			}
			if i > 0 && tx.ID <= hist[i-1].ID {
				t.Fatal("history must be oldest first")
			}
		}
		if hist[0].From != 0 || hist[0].To != a.ID || hist[1].From != a.ID || hist[1].To != 0 {
			t.Fatalf("deposit/withdraw sides wrong: %+v", hist[:2])
		}
		bHist, err := st.ListTransactions(ctx, b.ID)
		if err != nil || len(bHist) != 1 || bHist[0].ID != tr.ID {
			t.Fatalf("transfer must appear in receiver history: %+v, %v", bHist, err)
		}
		fresh := mustAccount(t, st, "Fresh", 0)
		if h, err := st.ListTransactions(ctx, fresh.ID); err != nil || h == nil || len(h) != 0 {
			t.Fatalf("new account history = %#v, %v; want empty non-nil slice", h, err)
		}
	})

	t.Run("errors", func(t *testing.T) {
		a := mustAccount(t, st, "Rich", 100)
		b := mustAccount(t, st, "Poor", 0)
		missing := unknownID(t, st)
		tests := []struct {
			name string
			op   func() error
			want error
		}{
			{"create one-rune owner", func() error { _, err := st.CreateAccount(ctx, "a"); return err }, bank.ErrInvalidOwner},
			{"create blank owner", func() error { _, err := st.CreateAccount(ctx, "   "); return err }, bank.ErrInvalidOwner},
			{"get bad id", func() error { _, err := st.GetAccount(ctx, 0); return err }, bank.ErrInvalidID},
			{"get unknown", func() error { _, err := st.GetAccount(ctx, missing); return err }, bank.ErrAccountNotFound},
			{"deposit zero", func() error { _, err := st.Deposit(ctx, a.ID, 0); return err }, bank.ErrInvalidAmount},
			{"deposit too much", func() error { _, err := st.Deposit(ctx, a.ID, bank.MaxAmount+1); return err }, bank.ErrInvalidAmount},
			{"deposit unknown", func() error { _, err := st.Deposit(ctx, missing, 10); return err }, bank.ErrAccountNotFound},
			{"invalid amount beats unknown", func() error { _, err := st.Deposit(ctx, missing, -1); return err }, bank.ErrInvalidAmount},
			{"withdraw negative", func() error { _, err := st.Withdraw(ctx, a.ID, -5); return err }, bank.ErrInvalidAmount},
			{"withdraw unknown", func() error { _, err := st.Withdraw(ctx, missing, 10); return err }, bank.ErrAccountNotFound},
			{"withdraw insufficient", func() error { _, err := st.Withdraw(ctx, b.ID, 10); return err }, bank.ErrInsufficientFunds},
			{"transfer same account", func() error { _, err := st.Transfer(ctx, a.ID, a.ID, 10); return err }, bank.ErrSameAccount},
			{"transfer unknown to", func() error { _, err := st.Transfer(ctx, a.ID, missing, 10); return err }, bank.ErrAccountNotFound},
			{"transfer unknown from", func() error { _, err := st.Transfer(ctx, missing, a.ID, 10); return err }, bank.ErrAccountNotFound},
			{"404 beats 409", func() error { _, err := st.Transfer(ctx, b.ID, missing, bank.MaxAmount); return err }, bank.ErrAccountNotFound},
			{"transfer insufficient", func() error { _, err := st.Transfer(ctx, b.ID, a.ID, 10); return err }, bank.ErrInsufficientFunds},
			{"history unknown", func() error { _, err := st.ListTransactions(ctx, missing); return err }, bank.ErrAccountNotFound},
		}
		for _, tt := range tests {
			t.Run(tt.name, func(t *testing.T) {
				if err := tt.op(); !errors.Is(err, tt.want) {
					t.Fatalf("got error %v, want %v", err, tt.want)
				}
			})
		}
		// Failed operations must not move money or write ledger rows.
		mustBalance(t, st, a.ID, 100)
		mustBalance(t, st, b.ID, 0)
		if h, _ := st.ListTransactions(ctx, b.ID); len(h) != 0 {
			t.Fatalf("failed operations wrote ledger rows: %+v", h)
		}
	})
}

// runConcurrencyStorm hammers one store from many goroutines and checks that
// not a single coin is lost or created. Run with -race.
func runConcurrencyStorm(t *testing.T, st Store) {
	t.Run("100 parallel deposits", func(t *testing.T) {
		acc := mustAccount(t, st, "Storm", 0)
		const n = 100
		var wg sync.WaitGroup
		errs := make(chan error, n)
		for range n {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if _, err := st.Deposit(ctx, acc.ID, 10); err != nil {
					errs <- err
				}
			}()
		}
		wg.Wait()
		close(errs)
		for err := range errs {
			t.Fatalf("deposit failed: %v", err)
		}
		mustBalance(t, st, acc.ID, n*10)
	})

	t.Run("50 parallel transfers, only 33 can succeed", func(t *testing.T) {
		x := mustAccount(t, st, "Sender", 1000)
		y := mustAccount(t, st, "Receiver", 0)
		var ok, insufficient atomic.Int64
		var wg sync.WaitGroup
		for range 50 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_, err := st.Transfer(ctx, x.ID, y.ID, 30)
				switch {
				case err == nil:
					ok.Add(1)
				case errors.Is(err, bank.ErrInsufficientFunds):
					insufficient.Add(1)
				default:
					t.Errorf("unexpected error: %v", err)
				}
			}()
		}
		wg.Wait()
		if ok.Load() != 33 || insufficient.Load() != 17 {
			t.Fatalf("ok=%d insufficient=%d, want 33 and 17", ok.Load(), insufficient.Load())
		}
		mustBalance(t, st, x.ID, 10)
		mustBalance(t, st, y.ID, 990)
	})

	// Transfers in both directions at once: with naive lock ordering this is
	// where Postgres deadlocks (bonus B4).
	t.Run("200 bidirectional transfers conserve money", func(t *testing.T) {
		p := mustAccount(t, st, "Ping", 1000)
		q := mustAccount(t, st, "Pong", 1000)
		var wg sync.WaitGroup
		errs := make(chan error, 200)
		for i := range 200 {
			from, to := p.ID, q.ID
			if i%2 == 1 {
				from, to = q.ID, p.ID
			}
			wg.Add(1)
			go func() {
				defer wg.Done()
				if _, err := st.Transfer(ctx, from, to, 7); err != nil {
					errs <- fmt.Errorf("transfer %d→%d: %w", from, to, err)
				}
			}()
		}
		wg.Wait()
		close(errs)
		for err := range errs {
			t.Fatal(err)
		}
		mustBalance(t, st, p.ID, 1000)
		mustBalance(t, st, q.ID, 1000)
	})
}
