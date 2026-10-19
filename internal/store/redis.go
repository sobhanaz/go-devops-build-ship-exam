package store

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"

	"snaplink/internal/link"
)

// Key design:
//
//	link:{code}  HASH  url, clicks, created_at[, expires_at]   (+ Redis TTL)
//	links        ZSET  member = code, score = created_at in unix ms
//
// With a TTL, Redis deletes the hash by itself; the ZSET entry is removed
// lazily by List (see unindexScript).
const indexKey = "links"

func linkKey(code string) string { return "link:" + code }

// createScript claims the code and writes the whole link in ONE atomic step.
// EXISTS + HSET as two separate client calls would let two parallel requests
// both see "free" and both get 201 (check-then-act race).
//
//	KEYS[1] = link:{code}  KEYS[2] = links
//	ARGV    = code, url, created_at (RFC 3339), score (unix ms),
//	          expires_at (RFC 3339 or ""), ttl in ms (or "")
var createScript = redis.NewScript(`
if redis.call('EXISTS', KEYS[1]) == 1 then
  return 0
end
redis.call('HSET', KEYS[1], 'url', ARGV[2], 'clicks', 0, 'created_at', ARGV[3])
if ARGV[5] ~= '' then
  redis.call('HSET', KEYS[1], 'expires_at', ARGV[5])
  redis.call('PEXPIRE', KEYS[1], ARGV[6])
end
redis.call('ZADD', KEYS[2], ARGV[4], ARGV[1])
return 1
`)

// hitScript counts a click and returns the url atomically.
//
// Why not just HINCRBY? HINCRBY on a missing key CREATES the hash, so a click
// that arrives right after (or long after) a DELETE would resurrect a broken
// link {clicks: 1}. And never HGET + HSET: two parallel requests would read
// the same value and one click would be lost. The script runs as one atomic
// step inside Redis, so EXISTS and HINCRBY cannot be interleaved.
//
//	KEYS[1] = link:{code}   returns url, or false (→ redis.Nil) if missing
var hitScript = redis.NewScript(`
if redis.call('EXISTS', KEYS[1]) == 0 then
  return false
end
redis.call('HINCRBY', KEYS[1], 'clicks', 1)
return redis.call('HGET', KEYS[1], 'url')
`)

// unindexScript removes a code from the ZSET only if its hash is really gone.
// A plain ZREM could race with a new link that re-uses the (now free) code.
var unindexScript = redis.NewScript(`
if redis.call('EXISTS', KEYS[1]) == 0 then
  return redis.call('ZREM', KEYS[2], ARGV[1])
end
return 0
`)

// Redis is the production Store backed by a go-redis client.
type Redis struct {
	rdb *redis.Client
}

// NewRedis wraps an existing client. The store owns it from now on (Close).
func NewRedis(rdb *redis.Client) *Redis {
	return &Redis{rdb: rdb}
}

func (s *Redis) Create(ctx context.Context, l link.Link) (link.Link, error) {
	expiresAt, ttlMillis := "", ""
	if l.ExpiresAt != nil {
		expiresAt = l.ExpiresAt.UTC().Format(time.RFC3339Nano)
		// Relative PEXPIRE (not PEXPIREAT) so clock skew between this pod
		// and the Redis host cannot shorten or stretch the TTL.
		ttlMillis = strconv.FormatInt(l.ExpiresAt.Sub(l.CreatedAt).Milliseconds(), 10)
	}
	ok, err := createScript.Run(ctx, s.rdb,
		[]string{linkKey(l.Code), indexKey},
		l.Code, l.URL, l.CreatedAt.UTC().Format(time.RFC3339Nano), l.CreatedAt.UnixMilli(),
		expiresAt, ttlMillis,
	).Int()
	if err != nil {
		return link.Link{}, fmt.Errorf("redis create: %w", err)
	}
	if ok == 0 {
		return link.Link{}, link.ErrCodeTaken
	}
	return l, nil
}

func (s *Redis) Get(ctx context.Context, code string) (link.Link, error) {
	vals, err := s.rdb.HGetAll(ctx, linkKey(code)).Result()
	if err != nil {
		return link.Link{}, fmt.Errorf("redis get: %w", err)
	}
	if len(vals) == 0 { // HGETALL on a missing key returns an empty map, not redis.Nil
		return link.Link{}, link.ErrNotFound
	}
	return parseLink(code, vals)
}

func (s *Redis) List(ctx context.Context) ([]link.Link, error) {
	codes, err := s.rdb.ZRevRange(ctx, indexKey, 0, -1).Result()
	if err != nil {
		return nil, fmt.Errorf("redis list: %w", err)
	}
	out := make([]link.Link, 0, len(codes))
	if len(codes) == 0 {
		return out, nil
	}

	// One round trip for all hashes instead of N.
	cmds := make([]*redis.MapStringStringCmd, len(codes))
	if _, err := s.rdb.Pipelined(ctx, func(p redis.Pipeliner) error {
		for i, code := range codes {
			cmds[i] = p.HGetAll(ctx, linkKey(code))
		}
		return nil
	}); err != nil {
		return nil, fmt.Errorf("redis list: %w", err)
	}

	var stale []string
	for i, cmd := range cmds {
		vals := cmd.Val()
		if len(vals) == 0 { // expired: Redis already dropped the hash
			stale = append(stale, codes[i])
			continue
		}
		l, err := parseLink(codes[i], vals)
		if err != nil {
			return nil, err
		}
		out = append(out, l)
	}

	// Lazy cleanup of the index. Best effort: if it fails, the entry is
	// simply skipped again next time.
	for _, code := range stale {
		_ = unindexScript.Run(ctx, s.rdb, []string{linkKey(code), indexKey}, code).Err()
	}
	return out, nil
}

func (s *Redis) Delete(ctx context.Context, code string) error {
	// MULTI/EXEC: the hash and its index entry disappear together.
	var del *redis.IntCmd
	if _, err := s.rdb.TxPipelined(ctx, func(p redis.Pipeliner) error {
		del = p.Del(ctx, linkKey(code))
		p.ZRem(ctx, indexKey, code)
		return nil
	}); err != nil {
		return fmt.Errorf("redis delete: %w", err)
	}
	if del.Val() == 0 {
		return link.ErrNotFound
	}
	return nil
}

func (s *Redis) Hit(ctx context.Context, code string) (string, error) {
	url, err := hitScript.Run(ctx, s.rdb, []string{linkKey(code)}).Text()
	if errors.Is(err, redis.Nil) { // the script returned false: no such link
		return "", link.ErrNotFound
	}
	if err != nil {
		return "", fmt.Errorf("redis hit: %w", err)
	}
	return url, nil
}

func (s *Redis) Ping(ctx context.Context) error {
	return s.rdb.Ping(ctx).Err()
}

// Close closes the underlying client (called on graceful shutdown).
func (s *Redis) Close() error {
	return s.rdb.Close()
}

func parseLink(code string, vals map[string]string) (link.Link, error) {
	clicks, err := strconv.ParseInt(vals["clicks"], 10, 64)
	if err != nil {
		return link.Link{}, fmt.Errorf("link %s: bad clicks %q: %w", code, vals["clicks"], err)
	}
	created, err := time.Parse(time.RFC3339Nano, vals["created_at"])
	if err != nil {
		return link.Link{}, fmt.Errorf("link %s: bad created_at: %w", code, err)
	}
	l := link.Link{Code: code, URL: vals["url"], Clicks: clicks, CreatedAt: created}
	if v, ok := vals["expires_at"]; ok {
		exp, err := time.Parse(time.RFC3339Nano, v)
		if err != nil {
			return link.Link{}, fmt.Errorf("link %s: bad expires_at: %w", code, err)
		}
		l.ExpiresAt = &exp
	}
	return l, nil
}
