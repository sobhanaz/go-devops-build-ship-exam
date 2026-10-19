package bank

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func TestNormalizeOwner(t *testing.T) {
	tests := []struct {
		name    string
		in      string
		want    string
		wantErr error
	}{
		{name: "plain", in: "Sara", want: "Sara"},
		{name: "trims spaces", in: "  Sara  ", want: "Sara"},
		{name: "trims tabs and newlines", in: "\tReza\n", want: "Reza"},
		{name: "minimum two runes", in: "Al", want: "Al"},
		{name: "persian counted in runes", in: "سارا", want: "سارا"},
		{name: "40 persian runes is 80 bytes but valid", in: strings.Repeat("ب", 40), want: strings.Repeat("ب", 40)},
		{name: "40 ascii runes", in: strings.Repeat("x", 40), want: strings.Repeat("x", 40)},
		{name: "one rune", in: "a", wantErr: ErrInvalidOwner},
		{name: "one persian rune (2 bytes)", in: "س", wantErr: ErrInvalidOwner},
		{name: "empty", in: "", wantErr: ErrInvalidOwner},
		{name: "only spaces", in: "     ", wantErr: ErrInvalidOwner},
		{name: "41 runes", in: strings.Repeat("x", 41), wantErr: ErrInvalidOwner},
		{name: "41 persian runes", in: strings.Repeat("ب", 41), wantErr: ErrInvalidOwner},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := NormalizeOwner(tt.in)
			if !errors.Is(err, tt.wantErr) {
				t.Fatalf("NormalizeOwner(%q) error = %v, want %v", tt.in, err, tt.wantErr)
			}
			if got != tt.want {
				t.Fatalf("NormalizeOwner(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}

func TestValidateAmount(t *testing.T) {
	tests := []struct {
		name    string
		amount  int64
		wantErr error
	}{
		{"one", 1, nil},
		{"typical", 500, nil},
		{"maximum", 1_000_000_000, nil},
		{"zero", 0, ErrInvalidAmount},
		{"negative", -5, ErrInvalidAmount},
		{"above maximum", 1_000_000_001, ErrInvalidAmount},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := ValidateAmount(tt.amount); !errors.Is(err, tt.wantErr) {
				t.Fatalf("ValidateAmount(%d) = %v, want %v", tt.amount, err, tt.wantErr)
			}
		})
	}
}

func TestValidateTransfer(t *testing.T) {
	tests := []struct {
		name             string
		from, to, amount int64
		wantErr          error
	}{
		{"valid", 1, 2, 300, nil},
		{"same account", 3, 3, 300, ErrSameAccount},
		{"zero from", 0, 2, 300, ErrInvalidID},
		{"negative to", 1, -2, 300, ErrInvalidID},
		{"zero amount", 1, 2, 0, ErrInvalidAmount},
		{"too large", 1, 2, 1_000_000_001, ErrInvalidAmount},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := ValidateTransfer(tt.from, tt.to, tt.amount); !errors.Is(err, tt.wantErr) {
				t.Fatalf("ValidateTransfer(%d, %d, %d) = %v, want %v", tt.from, tt.to, tt.amount, err, tt.wantErr)
			}
		})
	}
}

// The contract says the absent side of a deposit/withdraw is OMITTED from the
// JSON, not null and not 0.
func TestTransactionJSONOmitsAbsentSide(t *testing.T) {
	tests := []struct {
		name        string
		tx          Transaction
		wantKeys    []string
		missingKeys []string
	}{
		{"deposit", Transaction{ID: 1, Type: TxDeposit, To: 7, Amount: 5}, []string{"to"}, []string{"from"}},
		{"withdraw", Transaction{ID: 2, Type: TxWithdraw, From: 7, Amount: 5}, []string{"from"}, []string{"to"}},
		{"transfer", Transaction{ID: 3, Type: TxTransfer, From: 7, To: 8, Amount: 5}, []string{"from", "to"}, nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			raw, err := json.Marshal(tt.tx)
			if err != nil {
				t.Fatal(err)
			}
			var m map[string]any
			if err := json.Unmarshal(raw, &m); err != nil {
				t.Fatal(err)
			}
			for _, k := range tt.wantKeys {
				if _, ok := m[k]; !ok {
					t.Errorf("%s: key %q missing in %s", tt.name, k, raw)
				}
			}
			for _, k := range tt.missingKeys {
				if _, ok := m[k]; ok {
					t.Errorf("%s: key %q must be omitted in %s", tt.name, k, raw)
				}
			}
		})
	}
}
