// Package store is the persistence boundary of MiniBank.
//
// There are two implementations of Store: Memory (tests and quick local runs)
// and Postgres (compose and Kubernetes). main picks one from the STORE env var.
//
// Both implementations validate their input with the bank package before they
// look at any data. That gives the error precedence the contract asks for:
// 400 (invalid input) → 404 (account missing) → 409 (insufficient funds).
package store

import (
	"context"

	"minibank/internal/bank"
)

// Store is everything the HTTP layer needs from a datastore.
type Store interface {
	CreateAccount(ctx context.Context, owner string) (bank.Account, error)
	ListAccounts(ctx context.Context) ([]bank.Account, error)
	GetAccount(ctx context.Context, id int64) (bank.Account, error)
	Deposit(ctx context.Context, id, amount int64) (bank.Account, error)
	Withdraw(ctx context.Context, id, amount int64) (bank.Account, error)
	Transfer(ctx context.Context, from, to, amount int64) (bank.Transaction, error)
	ListTransactions(ctx context.Context, accountID int64) ([]bank.Transaction, error)
	// Ping reports whether the datastore is reachable (used by /readyz).
	Ping(ctx context.Context) error
	// Close releases connections. Called once during graceful shutdown.
	Close()
}
