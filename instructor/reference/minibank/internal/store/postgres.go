package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"minibank/internal/bank"
)

// Postgres is the production Store, backed by a pgx connection pool.
//
// Every query is parameterized ($1, $2, ...). SQL is never built with
// fmt.Sprintf, so user input can never become SQL.
type Postgres struct {
	pool *pgxpool.Pool
}

var _ Store = (*Postgres)(nil)

// The schema is created at startup. CHECK (balance >= 0) is the last line of
// defence: even a buggy query cannot make a balance negative.
var schema = []string{
	`CREATE TABLE IF NOT EXISTS accounts (
		id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
		owner      TEXT        NOT NULL,
		balance    BIGINT      NOT NULL DEFAULT 0 CHECK (balance >= 0),
		created_at TIMESTAMPTZ NOT NULL DEFAULT now()
	)`,
	`CREATE TABLE IF NOT EXISTS transactions (
		id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
		type       TEXT        NOT NULL CHECK (type IN ('deposit', 'withdraw', 'transfer')),
		from_id    BIGINT      REFERENCES accounts (id),
		to_id      BIGINT      REFERENCES accounts (id),
		amount     BIGINT      NOT NULL CHECK (amount > 0),
		created_at TIMESTAMPTZ NOT NULL DEFAULT now()
	)`,
	`CREATE INDEX IF NOT EXISTS transactions_from_id_idx ON transactions (from_id)`,
	`CREATE INDEX IF NOT EXISTS transactions_to_id_idx ON transactions (to_id)`,
}

// migrationLockID is an arbitrary constant for pg_advisory_xact_lock.
const migrationLockID = 7_312_026

// NewPostgres connects to databaseURL, checks the connection and creates the
// schema. ctx bounds the connect + migrate step only.
func NewPostgres(ctx context.Context, databaseURL string) (*Postgres, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse DATABASE_URL: %w", err)
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}
	p := &Postgres{pool: pool}
	if err := p.migrate(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return p, nil
}

// migrate creates the tables. Two replicas usually start at the same moment
// and concurrent CREATE TABLE IF NOT EXISTS can still collide in the system
// catalog, so the DDL runs under a transaction-scoped advisory lock.
func (p *Postgres) migrate(ctx context.Context) error {
	return pgx.BeginFunc(ctx, p.pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock($1)`, migrationLockID); err != nil {
			return fmt.Errorf("migration lock: %w", err)
		}
		for _, stmt := range schema {
			if _, err := tx.Exec(ctx, stmt); err != nil {
				return fmt.Errorf("migrate: %w", err)
			}
		}
		return nil
	})
}

const accountColumns = `id, owner, balance, created_at`

func scanAccount(row pgx.Row) (bank.Account, error) {
	var a bank.Account
	if err := row.Scan(&a.ID, &a.Owner, &a.Balance, &a.CreatedAt); err != nil {
		return bank.Account{}, err
	}
	a.CreatedAt = a.CreatedAt.UTC()
	return a, nil
}

func (p *Postgres) CreateAccount(ctx context.Context, owner string) (bank.Account, error) {
	owner, err := bank.NormalizeOwner(owner)
	if err != nil {
		return bank.Account{}, err
	}
	return scanAccount(p.pool.QueryRow(ctx,
		`INSERT INTO accounts (owner) VALUES ($1) RETURNING `+accountColumns, owner))
}

func (p *Postgres) ListAccounts(ctx context.Context) ([]bank.Account, error) {
	rows, err := p.pool.Query(ctx, `SELECT `+accountColumns+` FROM accounts ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]bank.Account, 0) // never nil → JSON [] not null
	for rows.Next() {
		a, err := scanAccount(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func (p *Postgres) GetAccount(ctx context.Context, id int64) (bank.Account, error) {
	if err := bank.ValidateID(id); err != nil {
		return bank.Account{}, err
	}
	a, err := scanAccount(p.pool.QueryRow(ctx,
		`SELECT `+accountColumns+` FROM accounts WHERE id = $1`, id))
	return a, notFound(err)
}

func (p *Postgres) Deposit(ctx context.Context, id, amount int64) (bank.Account, error) {
	if err := validateIDAndAmount(id, amount); err != nil {
		return bank.Account{}, err
	}
	var acc bank.Account
	// Balance update and ledger row commit together or not at all.
	err := pgx.BeginFunc(ctx, p.pool, func(tx pgx.Tx) error {
		var err error
		// "balance = balance + $1" is computed by Postgres under the row lock,
		// so concurrent deposits cannot overwrite each other (no lost update).
		acc, err = scanAccount(tx.QueryRow(ctx,
			`UPDATE accounts SET balance = balance + $1 WHERE id = $2 RETURNING `+accountColumns,
			amount, id))
		if err != nil {
			return notFound(err)
		}
		_, err = tx.Exec(ctx,
			`INSERT INTO transactions (type, to_id, amount) VALUES ('deposit', $1, $2)`, id, amount)
		return err
	})
	return acc, err
}

func (p *Postgres) Withdraw(ctx context.Context, id, amount int64) (bank.Account, error) {
	if err := validateIDAndAmount(id, amount); err != nil {
		return bank.Account{}, err
	}
	var acc bank.Account
	err := pgx.BeginFunc(ctx, p.pool, func(tx pgx.Tx) error {
		var err error
		// Conditional UPDATE: the funds check and the debit are ONE statement.
		// A separate SELECT-then-UPDATE would let two withdrawals both see the
		// old balance and both succeed (read-check-write race).
		acc, err = scanAccount(tx.QueryRow(ctx,
			`UPDATE accounts SET balance = balance - $1
			 WHERE id = $2 AND balance >= $1
			 RETURNING `+accountColumns,
			amount, id))
		if errors.Is(err, pgx.ErrNoRows) {
			// No row updated: either the account is missing (404) or it has
			// too little money (409). One extra query tells them apart.
			var exists bool
			if err := tx.QueryRow(ctx,
				`SELECT EXISTS (SELECT 1 FROM accounts WHERE id = $1)`, id).Scan(&exists); err != nil {
				return err
			}
			if !exists {
				return bank.ErrAccountNotFound
			}
			return bank.ErrInsufficientFunds
		}
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx,
			`INSERT INTO transactions (type, from_id, amount) VALUES ('withdraw', $1, $2)`, id, amount)
		return err
	})
	return acc, err
}

func (p *Postgres) Transfer(ctx context.Context, from, to, amount int64) (bank.Transaction, error) {
	if err := bank.ValidateTransfer(from, to, amount); err != nil {
		return bank.Transaction{}, err
	}
	var t bank.Transaction
	err := retryOnConflict(ctx, func() error {
		return pgx.BeginFunc(ctx, p.pool, func(tx pgx.Tx) error {
			var err error
			t, err = transferTx(ctx, tx, from, to, amount)
			return err
		})
	})
	return t, err
}

// transferTx runs inside ONE SQL transaction: both balance updates and the
// ledger row are committed together, or (on any error) rolled back together.
func transferTx(ctx context.Context, tx pgx.Tx, from, to, amount int64) (bank.Transaction, error) {
	// Lock both rows in ascending id order, never in from→to order.
	// If transfer A→B locked A then B while B→A locked B then A, each would
	// wait for the other forever and Postgres would abort one with a
	// deadlock (SQLSTATE 40P01 → HTTP 500). With one global order the second
	// transfer simply waits for the first to commit.
	balances := make(map[int64]int64, 2)
	for _, id := range []int64{min(from, to), max(from, to)} {
		var balance int64
		err := tx.QueryRow(ctx, `SELECT balance FROM accounts WHERE id = $1 FOR UPDATE`, id).Scan(&balance)
		if err != nil {
			return bank.Transaction{}, notFound(err)
		}
		balances[id] = balance
	}
	// Both accounts exist (404 was decided first); now the funds (409).
	// The rows are locked, so this balance cannot change before we update it.
	if balances[from] < amount {
		return bank.Transaction{}, bank.ErrInsufficientFunds
	}
	if _, err := tx.Exec(ctx, `UPDATE accounts SET balance = balance - $1 WHERE id = $2`, amount, from); err != nil {
		return bank.Transaction{}, err
	}
	if _, err := tx.Exec(ctx, `UPDATE accounts SET balance = balance + $1 WHERE id = $2`, amount, to); err != nil {
		return bank.Transaction{}, err
	}
	t := bank.Transaction{Type: bank.TxTransfer, From: from, To: to, Amount: amount}
	err := tx.QueryRow(ctx,
		`INSERT INTO transactions (type, from_id, to_id, amount) VALUES ('transfer', $1, $2, $3)
		 RETURNING id, created_at`, from, to, amount).Scan(&t.ID, &t.CreatedAt)
	t.CreatedAt = t.CreatedAt.UTC()
	return t, err
}

func (p *Postgres) ListTransactions(ctx context.Context, accountID int64) ([]bank.Transaction, error) {
	if err := bank.ValidateID(accountID); err != nil {
		return nil, err
	}
	var exists bool
	if err := p.pool.QueryRow(ctx,
		`SELECT EXISTS (SELECT 1 FROM accounts WHERE id = $1)`, accountID).Scan(&exists); err != nil {
		return nil, err
	}
	if !exists {
		return nil, bank.ErrAccountNotFound
	}
	// COALESCE turns a NULL side into 0, which omitempty then drops from JSON.
	rows, err := p.pool.Query(ctx,
		`SELECT id, type, COALESCE(from_id, 0), COALESCE(to_id, 0), amount, created_at
		 FROM transactions
		 WHERE from_id = $1 OR to_id = $1
		 ORDER BY id`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]bank.Transaction, 0)
	for rows.Next() {
		var t bank.Transaction
		var typ string
		if err := rows.Scan(&t.ID, &typ, &t.From, &t.To, &t.Amount, &t.CreatedAt); err != nil {
			return nil, err
		}
		t.Type = bank.TxType(typ)
		t.CreatedAt = t.CreatedAt.UTC()
		out = append(out, t)
	}
	return out, rows.Err()
}

func (p *Postgres) Ping(ctx context.Context) error { return p.pool.Ping(ctx) }

func (p *Postgres) Close() { p.pool.Close() }

// notFound translates "no row" into the domain error.
func notFound(err error) error {
	if errors.Is(err, pgx.ErrNoRows) {
		return bank.ErrAccountNotFound
	}
	return err
}

// retryOnConflict re-runs fn when Postgres aborted the transaction with a
// deadlock (40P01) or a serialization failure (40001). With id-ordered
// locking a deadlock should not happen at all; this is a safety net only.
func retryOnConflict(ctx context.Context, fn func() error) error {
	const attempts = 3
	var err error
	for i := range attempts {
		err = fn()
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || (pgErr.Code != "40P01" && pgErr.Code != "40001") {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(time.Duration(i+1) * 20 * time.Millisecond):
		}
	}
	return err
}
