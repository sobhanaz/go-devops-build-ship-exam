# My decisions (تصمیم‌های من) — MiniBank

Written at 0:00–0:10, before any code. Model answer for the "My decisions"
section (Q method) of PLAN.md.

## WHAT
A JSON REST ledger API in Go: create/list/get accounts, deposit, withdraw,
atomic transfers and per-account history, exactly as in the contract
(paths, field names, status codes). "Done" = auto-grader green against
Postgres (incl. the 100-deposit and 50-transfer storms), `go test -race`
green without a DB, smoke.sh green on compose and on kind.

## STRUCTURE
- `cmd/minibank` — config from env, store selection, server, graceful shutdown.
- `internal/bank` — `Account`, `Transaction`, validation, sentinel errors. No HTTP, no SQL.
- `internal/store` — `Store` interface + `Memory` (mutex) + `Postgres` (pgx pool).
- `internal/api` — routes (Go 1.22 ServeMux patterns), handlers, JSON helpers,
  ONE error→status function, middleware (slog JSON log, panic recovery), metrics.
- Dependencies point inwards: api → store → bank.

## DATA
- Money = `int64` minor units, never `float64`. Amount 1..1e9, else 400.
- Owner: `strings.TrimSpace`, then 2..40 **runes** (`utf8.RuneCountInString`).
- Postgres: `accounts(id identity, owner, balance BIGINT CHECK (balance >= 0), created_at)`
  and `transactions(id identity, type, from_id NULL, to_id NULL, amount, created_at)`.
  Created at startup with `CREATE TABLE IF NOT EXISTS`.
- JSON: `from`/`to` are `int64` with `omitempty` (ids are > 0, so 0 = absent).
  `created_at` in UTC, RFC 3339. Empty lists are `[]`, never `null`.

## CONCURRENCY
- Memory: one `sync.RWMutex` around all state; check-and-update under the same lock.
- Postgres deposit: `UPDATE … SET balance = balance + $1` (atomic in the DB).
- Withdraw: conditional `UPDATE … WHERE id = $2 AND balance >= $1`; 0 rows →
  `EXISTS` query decides 404 vs 409. No read-check-write.
- Transfer: ONE SQL transaction; `SELECT … FOR UPDATE` both rows in **ascending
  id order** (deadlock-free), check funds, two UPDATEs, INSERT ledger row, COMMIT.
  Retry on 40P01/40001 as a safety net.
- Error precedence by construction: validate (400) → lookups (404) → funds (409).

## SECURITY
- Only parameterized SQL (`$1`, `$2`), never `fmt.Sprintf` SQL.
- Secrets only from env (`DATABASE_URL`); `.env` git-ignored, `.env.example`
  committed; K8s Secret via `secretKeyRef`. The URL is never logged.
- `http.MaxBytesReader` 1 MB, server timeouts (ReadHeaderTimeout etc.).
- 500s log the detail but return only `{"error":"internal error"}`.
- Container: static binary on `scratch`, `USER 65532`, read-only root FS in K8s.
- DB port not published in compose; ClusterIP in K8s.

## OUT OF SCOPE
Authentication/users, currencies, pagination, deleting/closing accounts,
idempotency keys, overdrafts, HA Postgres (StatefulSet + replication), TLS.

## RISKS + fallback
| Risk | Fallback |
|---|---|
| Postgres store late or broken at 1:00 | ship with `STORE=memory` (still passes the API + storms), finish pg later |
| Deadlocks under bidirectional storm | lock order by id + retry on 40P01 |
| kind / image loading trouble | `kind load docker-image`, `imagePullPolicy: IfNotPresent`; worst case demo with compose |
| Time runs out | bonus last; README + AI note at 2:50 no matter what |
| Two replicas run migrations at once | `pg_advisory_xact_lock` around the DDL |

## AI PLAN
- Use AI for boilerplate (handlers, JSON helpers, YAML, scripts) and for
  reviewing my concurrency code — not for decisions I cannot explain.
- I write the transfer SQL and the lock order myself, then ask AI to try to break it.
- Every AI suggestion must pass `go vet`, `go test -race` and the storm before it is committed.
- Check AI output for: `float64` money, byte-length (`len()`) owner checks,
  read-check-write transfers, `fmt.Sprintf` SQL, `null` instead of `[]`.
