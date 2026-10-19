package link

import (
	"regexp"
	"testing"
)

var codeRE = regexp.MustCompile(`^[A-Za-z0-9]{6}$`)

func TestNewCode(t *testing.T) {
	seen := make(map[string]bool)
	for i := 0; i < 2000; i++ {
		code, err := NewCode()
		if err != nil {
			t.Fatalf("NewCode: %v", err)
		}
		if !codeRE.MatchString(code) {
			t.Fatalf("NewCode() = %q, want 6 base62 characters", code)
		}
		if IsReserved(code) {
			t.Fatalf("NewCode() returned reserved word %q", code)
		}
		seen[code] = true
	}
	// 2000 draws from 62^6: a duplicate would point to a broken generator.
	if len(seen) != 2000 {
		t.Fatalf("got %d unique codes out of 2000", len(seen))
	}
}
