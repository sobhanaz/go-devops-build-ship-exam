package store

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"snaplink/internal/link"
)

// runContract checks the behaviour every Store must have. It runs against
// Memory always, and against Redis when SNAPLINK_TEST_REDIS_ADDR is set.
// Codes are random so it also works on a Redis that already has data.
func runContract(t *testing.T, st Store) {
	ctx := context.Background()

	t.Run("create then get", func(t *testing.T) {
		l := mustCreate(t, st, newLink(t, st, "https://go.dev/doc"))
		got, err := st.Get(ctx, l.Code)
		if err != nil {
			t.Fatalf("Get: %v", err)
		}
		if got.URL != l.URL || got.Clicks != 0 || !got.CreatedAt.Equal(l.CreatedAt) {
			t.Fatalf("Get = %+v, want %+v", got, l)
		}
	})

	t.Run("duplicate code is ErrCodeTaken", func(t *testing.T) {
		l := mustCreate(t, st, newLink(t, st, "https://a.example"))
		dup := l
		dup.URL = "https://b.example"
		if _, err := st.Create(ctx, dup); !errors.Is(err, link.ErrCodeTaken) {
			t.Fatalf("second Create err = %v, want ErrCodeTaken", err)
		}
		if got, _ := st.Get(ctx, l.Code); got.URL != l.URL {
			t.Fatalf("duplicate create overwrote url: %q", got.URL)
		}
	})

	t.Run("unknown code is ErrNotFound everywhere", func(t *testing.T) {
		code := randomCode(t)
		if _, err := st.Get(ctx, code); !errors.Is(err, link.ErrNotFound) {
			t.Errorf("Get err = %v, want ErrNotFound", err)
		}
		if _, err := st.Hit(ctx, code); !errors.Is(err, link.ErrNotFound) {
			t.Errorf("Hit err = %v, want ErrNotFound", err)
		}
		if err := st.Delete(ctx, code); !errors.Is(err, link.ErrNotFound) {
			t.Errorf("Delete err = %v, want ErrNotFound", err)
		}
	})

	t.Run("hit returns url and counts", func(t *testing.T) {
		l := mustCreate(t, st, newLink(t, st, "https://example.com/hit"))
		for i := 0; i < 3; i++ {
			url, err := st.Hit(ctx, l.Code)
			if err != nil || url != l.URL {
				t.Fatalf("Hit = %q, %v; want %q", url, err, l.URL)
			}
		}
		if got, _ := st.Get(ctx, l.Code); got.Clicks != 3 {
			t.Fatalf("clicks = %d, want 3", got.Clicks)
		}
	})

	t.Run("delete removes link and index entry", func(t *testing.T) {
		l := mustCreate(t, st, newLink(t, st, "https://example.com/del"))
		if err := st.Delete(ctx, l.Code); err != nil {
			t.Fatalf("Delete: %v", err)
		}
		if _, err := st.Get(ctx, l.Code); !errors.Is(err, link.ErrNotFound) {
			t.Fatalf("Get after delete err = %v, want ErrNotFound", err)
		}
		if containsCode(t, st, l.Code) {
			t.Fatalf("deleted code %s still listed", l.Code)
		}
		if err := st.Delete(ctx, l.Code); !errors.Is(err, link.ErrNotFound) {
			t.Fatalf("second Delete err = %v, want ErrNotFound", err)
		}
	})

	t.Run("hit after delete does not resurrect the link", func(t *testing.T) {
		l := mustCreate(t, st, newLink(t, st, "https://example.com/zombie"))
		if err := st.Delete(ctx, l.Code); err != nil {
			t.Fatalf("Delete: %v", err)
		}
		if _, err := st.Hit(ctx, l.Code); !errors.Is(err, link.ErrNotFound) {
			t.Fatalf("Hit after delete err = %v, want ErrNotFound", err)
		}
		if _, err := st.Get(ctx, l.Code); !errors.Is(err, link.ErrNotFound) {
			t.Fatalf("Get after hit-after-delete err = %v, want ErrNotFound", err)
		}
	})

	t.Run("list is newest first", func(t *testing.T) {
		base := time.Now().UTC().Truncate(time.Millisecond).Add(time.Hour) // newer than anything else
		var codes []string
		for i := 0; i < 3; i++ {
			l := newLink(t, st, "https://example.com/list")
			l.CreatedAt = base.Add(time.Duration(i) * time.Millisecond)
			codes = append(codes, mustCreate(t, st, l).Code)
		}
		all, err := st.List(ctx)
		if err != nil {
			t.Fatalf("List: %v", err)
		}
		if all == nil {
			t.Fatal("List returned nil, want a non-nil slice")
		}
		pos := map[string]int{}
		for i, l := range all {
			pos[l.Code] = i
			if i > 0 && l.CreatedAt.After(all[i-1].CreatedAt) {
				t.Fatalf("List not newest first at index %d", i)
			}
		}
		if !(pos[codes[2]] < pos[codes[1]] && pos[codes[1]] < pos[codes[0]]) {
			t.Fatalf("order of our codes = %d,%d,%d; want newest first", pos[codes[2]], pos[codes[1]], pos[codes[0]])
		}
	})

	t.Run("expired link is gone everywhere and its code is free again", func(t *testing.T) {
		l := newLink(t, st, "https://example.com/ttl")
		exp := l.CreatedAt.Add(300 * time.Millisecond)
		l.ExpiresAt = &exp
		mustCreate(t, st, l)

		got, err := st.Get(ctx, l.Code)
		if err != nil || got.ExpiresAt == nil || !got.ExpiresAt.Equal(exp) {
			t.Fatalf("Get before expiry = %+v, %v; want expires_at %v", got, err, exp)
		}
		if _, err := st.Hit(ctx, l.Code); err != nil {
			t.Fatalf("Hit before expiry: %v", err)
		}

		time.Sleep(400 * time.Millisecond)
		if _, err := st.Hit(ctx, l.Code); !errors.Is(err, link.ErrNotFound) {
			t.Errorf("Hit after expiry err = %v, want ErrNotFound", err)
		}
		if _, err := st.Get(ctx, l.Code); !errors.Is(err, link.ErrNotFound) {
			t.Errorf("Get after expiry err = %v, want ErrNotFound", err)
		}
		if containsCode(t, st, l.Code) {
			t.Errorf("expired code %s still listed", l.Code)
		}
		fresh := l
		fresh.ExpiresAt = nil
		if _, err := st.Create(ctx, fresh); err != nil {
			t.Errorf("re-using an expired code: %v", err)
		}
	})

	// The click storm: 200 goroutines hit the SAME code. With a non-atomic
	// read-modify-write some increments would be lost and clicks < 200.
	t.Run("concurrent hits are all counted", func(t *testing.T) {
		l := mustCreate(t, st, newLink(t, st, "https://example.com/storm"))
		const n = 200
		var wg sync.WaitGroup
		errs := make(chan error, n)
		for i := 0; i < n; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if _, err := st.Hit(ctx, l.Code); err != nil {
					errs <- err
				}
			}()
		}
		wg.Wait()
		close(errs)
		for err := range errs {
			t.Fatalf("Hit: %v", err)
		}
		if got, _ := st.Get(ctx, l.Code); got.Clicks != n {
			t.Fatalf("clicks = %d, want exactly %d", got.Clicks, n)
		}
	})

	// 50 goroutines race to claim one custom code: exactly one may win.
	t.Run("concurrent create of one code has exactly one winner", func(t *testing.T) {
		l := newLink(t, st, "https://example.com/claim")
		const n = 50
		var wg sync.WaitGroup
		var mu sync.Mutex
		wins, taken := 0, 0
		for i := 0; i < n; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_, err := st.Create(ctx, l)
				mu.Lock()
				defer mu.Unlock()
				switch {
				case err == nil:
					wins++
				case errors.Is(err, link.ErrCodeTaken):
					taken++
				default:
					t.Errorf("Create: %v", err)
				}
			}()
		}
		wg.Wait()
		if wins != 1 || taken != n-1 {
			t.Fatalf("wins=%d taken=%d, want 1 and %d", wins, taken, n-1)
		}
	})
}

// newLink returns an unsaved link with a fresh random code and registers a
// cleanup so shared Redis instances are left as we found them.
func newLink(t *testing.T, st Store, url string) link.Link {
	t.Helper()
	code := randomCode(t)
	t.Cleanup(func() { _ = st.Delete(context.Background(), code) })
	return link.Link{Code: code, URL: url, CreatedAt: time.Now().UTC().Truncate(time.Millisecond)}
}

func randomCode(t *testing.T) string {
	t.Helper()
	c, err := link.NewCode()
	if err != nil {
		t.Fatal(err)
	}
	return "t_" + c
}

func mustCreate(t *testing.T, st Store, l link.Link) link.Link {
	t.Helper()
	created, err := st.Create(context.Background(), l)
	if err != nil {
		t.Fatalf("Create(%s): %v", l.Code, err)
	}
	return created
}

func containsCode(t *testing.T, st Store, code string) bool {
	t.Helper()
	all, err := st.List(context.Background())
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	for _, l := range all {
		if l.Code == code {
			return true
		}
	}
	return false
}
