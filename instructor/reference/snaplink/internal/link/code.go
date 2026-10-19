package link

import (
	"crypto/rand"
	"math/big"
)

// CodeLength is the length of generated codes. 62^6 ≈ 5.7e10 possibilities.
const CodeLength = 6

const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

var alphabetSize = big.NewInt(int64(len(alphabet)))

// NewCode returns a random 6-character base62 code.
//
// It uses crypto/rand, not math/rand: math/rand output is predictable, so
// anyone could enumerate the links other people created. rand.Int draws
// uniformly from [0,62), so there is no modulo bias either.
func NewCode() (string, error) {
	for {
		b := make([]byte, CodeLength)
		for i := range b {
			n, err := rand.Int(rand.Reader, alphabetSize)
			if err != nil {
				return "", err
			}
			b[i] = alphabet[n.Int64()]
		}
		// "readyz" is 6 letters: astronomically unlikely, but a generated
		// code must never be a reserved route name.
		if code := string(b); !IsReserved(code) {
			return code, nil
		}
	}
}
