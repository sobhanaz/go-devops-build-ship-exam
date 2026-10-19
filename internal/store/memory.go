package store

import (
	"cmp"
	"context"
	"slices"
	"sync"
	"time"

	"minibank/internal/bank"
)

// Memory is a concurrency-safe in-memory Store.
//
// One mutex guards ALL state. A transfer touches two accounts and the ledger,
// so per-account locks would need a lock order to avoid deadlocks; a single
// lock is simpler, cannot deadlock and is fast enough for an in-process map.
//
// Memory is per process: with 2 replicas each pod has its own bank, which is
// why Kubernetes runs with STORE=postgres.
type Memory struct {
	mu            sync.RWMutex
	accounts      map[int64]bank.Account
	txs           []bank.Transaction // append-only, so it is always in id order
	lastAccountID int64
	lastTxID      int64
}

var _ Store = (*Memory)(nil)

// NewMemory returns an empty in-memory store.
func NewMemory() *Memory {
	return &Memory{accounts: make(map[int64]bank.Account)}
}

func now() time.Time { return time.Now().UTC() }

func (m *Memory) CreateAccount(_ context.Context, owner string) (bank.Account, error) {
	owner, err := bank.NormalizeOwner(owner)
	if err != nil {
		return bank.Account{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.lastAccountID++
	acc := bank.Account{ID: m.lastAccountID, Owner: owner, CreatedAt: now()}
	m.accounts[acc.ID] = acc
	return acc, nil
}

func (m *Memory) ListAccounts(_ context.Context) ([]bank.Account, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]bank.Account, 0, len(m.accounts)) // never nil → JSON [] not null
	for _, acc := range m.accounts {
		out = append(out, acc)
	}
	slices.SortFunc(out, func(a, b bank.Account) int { return cmp.Compare(a.ID, b.ID) })
	return out, nil
}

func (m *Memory) GetAccount(_ context.Context, id int64) (bank.Account, error) {
	if err := bank.ValidateID(id); err != nil {
		return bank.Account{}, err
	}
	m.mu.RLock()
	defer m.mu.RUnlock()
	acc, ok := m.accounts[id]
	if !ok {
		return bank.Account{}, bank.ErrAccountNotFound
	}
	return acc, nil
}

func (m *Memory) Deposit(_ context.Context, id, amount int64) (bank.Account, error) {
	if err := validateIDAndAmount(id, amount); err != nil {
		return bank.Account{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	acc, ok := m.accounts[id]
	if !ok {
		return bank.Account{}, bank.ErrAccountNotFound
	}
	acc.Balance += amount
	m.accounts[id] = acc
	m.recordLocked(bank.TxDeposit, 0, id, amount)
	return acc, nil
}

func (m *Memory) Withdraw(_ context.Context, id, amount int64) (bank.Account, error) {
	if err := validateIDAndAmount(id, amount); err != nil {
		return bank.Account{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	acc, ok := m.accounts[id]
	if !ok {
		return bank.Account{}, bank.ErrAccountNotFound
	}
	// Check and update happen under the same lock: no other goroutine can
	// spend the money between the check and the write.
	if acc.Balance < amount {
		return bank.Account{}, bank.ErrInsufficientFunds
	}
	acc.Balance -= amount
	m.accounts[id] = acc
	m.recordLocked(bank.TxWithdraw, id, 0, amount)
	return acc, nil
}

func (m *Memory) Transfer(_ context.Context, from, to, amount int64) (bank.Transaction, error) {
	if err := bank.ValidateTransfer(from, to, amount); err != nil {
		return bank.Transaction{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	src, okFrom := m.accounts[from]
	dst, okTo := m.accounts[to]
	if !okFrom || !okTo { // 404 is decided before 409
		return bank.Transaction{}, bank.ErrAccountNotFound
	}
	if src.Balance < amount {
		return bank.Transaction{}, bank.ErrInsufficientFunds
	}
	src.Balance -= amount
	dst.Balance += amount
	m.accounts[from] = src
	m.accounts[to] = dst
	return m.recordLocked(bank.TxTransfer, from, to, amount), nil
}

func (m *Memory) ListTransactions(_ context.Context, accountID int64) ([]bank.Transaction, error) {
	if err := bank.ValidateID(accountID); err != nil {
		return nil, err
	}
	m.mu.RLock()
	defer m.mu.RUnlock()
	if _, ok := m.accounts[accountID]; !ok {
		return nil, bank.ErrAccountNotFound
	}
	out := make([]bank.Transaction, 0)
	for _, tx := range m.txs {
		if tx.From == accountID || tx.To == accountID {
			out = append(out, tx)
		}
	}
	return out, nil
}

func (m *Memory) Ping(context.Context) error { return nil }

func (m *Memory) Close() {}

// recordLocked appends a ledger entry. The caller must hold m.mu for writing.
func (m *Memory) recordLocked(typ bank.TxType, from, to, amount int64) bank.Transaction {
	m.lastTxID++
	tx := bank.Transaction{ID: m.lastTxID, Type: typ, From: from, To: to, Amount: amount, CreatedAt: now()}
	m.txs = append(m.txs, tx)
	return tx
}

func validateIDAndAmount(id, amount int64) error {
	if err := bank.ValidateID(id); err != nil {
		return err
	}
	return bank.ValidateAmount(amount)
}
