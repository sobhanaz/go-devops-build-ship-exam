// Package bank is the MiniBank domain: accounts, ledger transactions, the
// validation rules and the sentinel errors that every other layer speaks.
//
// It has no dependencies on HTTP or on a database, so the rules are easy to
// test and are the same whichever store is used.
package bank

import (
	"errors"
	"strings"
	"time"
	"unicode/utf8"
)

// Money is always an int64 in the smallest unit (cents, Toman, ...).
// Never float64: 0.1+0.2 != 0.3 in binary floating point and a ledger must
// add up to the last coin.
const (
	MinOwnerRunes = 2
	MaxOwnerRunes = 40

	MinAmount int64 = 1
	MaxAmount int64 = 1_000_000_000
)

// Sentinel errors. Callers compare with errors.Is; the HTTP layer maps each
// of them to a status code in exactly one place (api.statusFor).
var (
	ErrInvalidOwner      = errors.New("owner must be 2 to 40 characters long")
	ErrInvalidAmount     = errors.New("amount must be an integer between 1 and 1000000000")
	ErrInvalidID         = errors.New("id must be a positive integer")
	ErrSameAccount       = errors.New("from and to must be different accounts")
	ErrAccountNotFound   = errors.New("account not found")
	ErrInsufficientFunds = errors.New("insufficient funds")
)

// Account is one customer account.
type Account struct {
	ID        int64     `json:"id"`
	Owner     string    `json:"owner"`
	Balance   int64     `json:"balance"`
	CreatedAt time.Time `json:"created_at"`
}

// TxType is the kind of a ledger entry.
type TxType string

const (
	TxDeposit  TxType = "deposit"
	TxWithdraw TxType = "withdraw"
	TxTransfer TxType = "transfer"
)

// Transaction is one ledger entry.
//
// From and To use omitempty: ids are always > 0, so 0 means "not set" and the
// key disappears from the JSON. A deposit has only "to", a withdraw only
// "from", a transfer both.
type Transaction struct {
	ID        int64     `json:"id"`
	Type      TxType    `json:"type"`
	From      int64     `json:"from,omitempty"`
	To        int64     `json:"to,omitempty"`
	Amount    int64     `json:"amount"`
	CreatedAt time.Time `json:"created_at"`
}

// NormalizeOwner trims surrounding white space and checks the length in
// runes, not bytes: "سارا" is 4 runes but 8 bytes and must be accepted.
func NormalizeOwner(raw string) (string, error) {
	owner := strings.TrimSpace(raw)
	n := utf8.RuneCountInString(owner)
	if n < MinOwnerRunes || n > MaxOwnerRunes {
		return "", ErrInvalidOwner
	}
	return owner, nil
}

// ValidateAmount accepts 1 ≤ amount ≤ 1e9.
func ValidateAmount(amount int64) error {
	if amount < MinAmount || amount > MaxAmount {
		return ErrInvalidAmount
	}
	return nil
}

// ValidateID accepts positive ids only.
func ValidateID(id int64) error {
	if id <= 0 {
		return ErrInvalidID
	}
	return nil
}

// ValidateTransfer checks everything about a transfer that can be decided
// without looking at the data. These are the 400 errors, and they are
// checked before any lookup so that 400 always wins over 404 and 409.
func ValidateTransfer(from, to, amount int64) error {
	if err := ValidateID(from); err != nil {
		return err
	}
	if err := ValidateID(to); err != nil {
		return err
	}
	if from == to {
		return ErrSameAccount
	}
	return ValidateAmount(amount)
}
