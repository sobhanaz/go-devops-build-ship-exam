# SnapLink — My decisions (Q method)

Written at 0:00–0:10, before any code. Short, specific, and something I can defend.

### 1. WHAT
A URL shortener microservice: `POST /api/links` turns a long http(s) URL into a
6-char code (or a custom code), `GET /{code}` answers `302` and counts the click,
plus list / get / delete. Success = the contract in CONTRACT-B is met byte-for-byte
and no click is ever lost under 100 parallel redirects.

### 2. STRUCTURE
- `cmd/snaplink` – config from env, store selection, HTTP server, graceful shutdown.
- `internal/link` – `Link` type, URL + code validation, crypto/rand base62 generator, sentinel errors. No HTTP, no Redis.
- `internal/store` – `Store` interface + `Memory` (mutex) + `Redis` (go-redis v9).
- `internal/api` – ServeMux routes, handlers, JSON helpers, ONE `statusFor(err)` mapping, middleware.
Dependencies point inwards: api → store → link. Handlers only see the interface.

### 3. DATA
Redis keys:
- `link:{code}` HASH `url`, `clicks`, `created_at` (RFC 3339, ms precision), optional `expires_at`.
- `links` ZSET member = code, score = created_at in unix ms → `ZREVRANGE` gives newest first.
- Create = Lua: `EXISTS` → `HSET` + `ZADD` (+ `PEXPIREAT` for TTL) in one atomic step.
- Delete = `MULTI { DEL link:{code}; ZREM links code }`.
Memory store: `map[string]entry` with a sequence number to break `created_at` ties.

### 4. CONCURRENCY
- Clicks: Redis `HINCRBY` inside a Lua script that first checks `EXISTS` → atomic, and a click on a deleted link cannot recreate the hash. Never GET-then-SET.
- Custom code claim: decided inside the same Lua script as the write, so 20 parallel POSTs → exactly one 201.
- Memory store: one `sync.Mutex` around the map (every method may mutate because of lazy TTL cleanup, so an RWMutex buys nothing). Proven by a 200-goroutine test with `-race`.

### 5. SECURITY
- Only `http`/`https` URLs with a host, ≤ 2048 chars → no `javascript:` / `data:` open-redirect or XSS links.
- Codes from `crypto/rand` (not guessable like `math/rand`), custom codes limited to `[A-Za-z0-9_-]{3,32}`, reserved words blocked so nobody can shadow `/healthz`.
- `http.MaxBytesReader` 1 MB, server read/write timeouts.
- Redis password only from env (`.env` locally, k8s Secret in the cluster); no secret in Go code or git. Container runs as non-root on `scratch`.

### 6. OUT OF SCOPE
Users/auth, rate limiting, analytics per click (referrer, geo), editing a link, pagination, HTTPS termination (Ingress does that), Redis persistence tuning / Sentinel.

### 7. RISKS + fallback
- Redis Lua / go-redis API takes too long → fallback: `HSETNX` claim + `TxPipelined` for the rest; still atomic enough for the storm tests.
- Docker daemon or kind broken on my laptop → finish manifests + CI, show `docker compose config` / `kubectl apply --dry-run=client`, explain in README.
- Running out of time → order: core API + tests (S1/S2) → Docker/Compose → CI → k8s → bonus last.

### 8. AI PLAN
- Use AI for: boilerplate (Dockerfile, manifests, Helm templates), test tables, README wording.
- Write / review myself: the Redis key design, the Lua scripts, error→status mapping, concurrency code.
- Rule: every AI snippet must pass `go vet`, `go test -race` and the smoke script before I commit it, and I must be able to explain each line in the defense.
