# SnapLink

![CI](https://github.com/<your-user>/snaplink/actions/workflows/ci.yml/badge.svg)

A small URL-shortener microservice in Go: create a short link (random or custom
code), `GET /{code}` redirects with `302` and counts the click, plus list, get
and delete. Clicks are counted atomically in Redis, so no click is lost under
hundreds of parallel requests. Shipped with Bash scripts, Docker, Compose,
GitHub Actions and Kubernetes (plus Helm).

Design decisions: see [DECISIONS.md](DECISIONS.md).

## API

| Method & path | Body | Success | Errors |
|---|---|---|---|
| `GET /healthz` | – | `200 {"status":"ok"}` (never touches Redis) | – |
| `GET /readyz` | – | `200 {"status":"ready"}` | `503 {"status":"not ready"}` |
| `POST /api/links` | `{"url":"https://go.dev"}`, optional `"code"`, `"ttl_seconds"` | `201` Link | `400`, `409` |
| `GET /api/links` | – | `200` array, newest first, `[]` when empty | – |
| `GET /api/links/{code}` | – | `200` Link | `404` |
| `DELETE /api/links/{code}` | – | `204` | `404` |
| `GET /{code}` | – | `302` + `Location`, clicks + 1 | `404` |
| `GET /metrics` | – | Prometheus text format | – |

```json
{"code":"aB3xK9","url":"https://go.dev/doc","short_url":"http://localhost:8080/aB3xK9","clicks":0,"created_at":"2026-10-20T09:30:00Z"}
```

```bash
curl -s -X POST localhost:8080/api/links -d '{"url":"https://go.dev/doc"}'
curl -s -X POST localhost:8080/api/links -d '{"url":"https://go.dev","code":"go-docs"}'
curl -si localhost:8080/go-docs            # 302 Location: https://go.dev
curl -s localhost:8080/api/links/go-docs   # clicks: 1
```

## Architecture

```
                 ┌──────────────────────── snaplink (Go, net/http) ────────────────────────┐
  client ──HTTP──▶ middleware: slog JSON log · panic recovery · Prometheus metrics         │
                 │        │                                                                │
                 │        ▼                                                                │
                 │  ServeMux (Go 1.22 patterns)  ──▶  handlers (internal/api)              │
                 │                                     │ validate (internal/link)          │
                 │                                     ▼                                   │
                 │                          store.Store interface                          │
                 │                          ├── Memory  (map + sync.Mutex)  STORE=memory   │
                 │                          └── Redis   (go-redis v9)       STORE=redis ───┼──▶ Redis 7
                 └─────────────────────────────────────────────────────────────────────────┘
                                                                     link:{code} HASH, links ZSET

  Kubernetes (namespace snaplink):
  port-forward / Ingress snaplink.local ──▶ Service snaplink :80 ──▶ Deployment snaplink ×2 :8080
                                                                        │ envFrom ConfigMap, Secret
                                                                        ▼
                                                     Service redis :6379 ──▶ Deployment redis ×1
```

Redis keys: `link:{code}` is a HASH (`url`, `clicks`, `created_at`, optional
`expires_at`); `links` is a ZSET (member = code, score = created_at in unix ms)
used to list newest first. Create and Hit are small Lua scripts so the code
claim and the click increment are atomic; Delete is a `MULTI` with `DEL` + `ZREM`.

## Run it

### 1. Locally with the in-memory store (no Redis needed)

```bash
STORE=memory go run ./cmd/snaplink
scripts/smoke.sh            # in another terminal
```

### 2. Locally against a Redis

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine --requirepass secret
REDIS_PASSWORD=secret go run ./cmd/snaplink
```

### 3. Docker Compose (app + Redis)

```bash
cp .env.example .env              # set REDIS_PASSWORD (optional on a laptop)
docker compose up -d --build
scripts/smoke.sh http://localhost:8080
docker compose down               # data survives in the redis-data volume (no -v!)
```

Redis has a healthcheck (`redis-cli ping`), the app waits for it with
`condition: service_healthy`, and the Redis port is not published to the host.

### 4. Kubernetes with kind

```bash
kind create cluster
docker build -t snaplink:v1 .
kind load docker-image snaplink:v1          # imagePullPolicy: IfNotPresent uses it
kubectl apply -f k8s/
kubectl -n snaplink rollout status deploy/snaplink
kubectl -n snaplink port-forward svc/snaplink 8080:80
scripts/smoke.sh http://localhost:8080      # in another terminal
```

(minikube: `minikube image load snaplink:v1` instead of `kind load`.)

`k8s/` is applied in file order: `00-namespace`, `10-configmap`, `11-secret`,
`20-redis`, `30-app`, `40-ingress`. Redis uses an `emptyDir`: it survives
container restarts but not pod rescheduling — acceptable for the exam, a
StatefulSet + PVC would be the production answer.

### 5. Helm (bonus)

```bash
helm install snaplink charts/snaplink -n snaplink --create-namespace
helm upgrade snaplink charts/snaplink -n snaplink --set replicaCount=3
```

Use either `kubectl apply -f k8s/` **or** Helm in a namespace, not both.

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `STORE` | `redis` | `redis` or `memory` (memory = one replica only!) |
| `REDIS_ADDR` | `localhost:6379` | Redis address |
| `REDIS_PASSWORD` | empty | Redis password (`.env` in compose, Secret in k8s) |
| `BASE_URL` | `http://localhost:8080` | prefix of `short_url`, no trailing slash |

Invalid values (e.g. `STORE=postgres`, `PORT=abc`) stop the service at start-up
with one clear JSON log line. An unreachable Redis does **not** stop it:
`/readyz` returns `503` until Redis answers, `/healthz` stays `200`.

## Tests & scripts

```bash
gofmt -l . && go vet ./...
go test -race ./...                                   # no Redis needed
SNAPLINK_TEST_REDIS_ADDR=localhost:6379 SNAPLINK_TEST_REDIS_PASSWORD=secret \
  go test -race ./internal/store/                      # + Redis integration test
scripts/check-env.sh                                  # go, git, docker, kubectl, kind/minikube
scripts/smoke.sh [BASE_URL]                           # 15 black-box checks, exit 1 on failure
```

- `internal/link`: table-driven URL / code validation (`errors.Is`), generator test.
- `internal/store`: one contract test suite run against Memory and (optionally)
  Redis, including a 200-goroutine click storm and a 50-goroutine code-claim race.
- `internal/api`: `httptest` tests for every endpoint, route precedence, panic recovery.

## Bonus

- **B1 metrics** — `GET /metrics`: `http_requests_total{method,path,status}`
  (path is the route pattern such as `/{code}`, never the raw URL, to keep label
  cardinality bounded), `http_request_duration_seconds`, `snaplink_redirects_total`,
  `snaplink_links_created_total`.
- **B2 Ingress** — `k8s/40-ingress.yaml`, host `snaplink.local` (needs the
  ingress-nginx controller; add `127.0.0.1 snaplink.local` to `/etc/hosts` and
  set `BASE_URL` to `http://snaplink.local`; the file shows how to test it with
  a port-forward to the controller).
- **B3 Helm** — `charts/snaplink` (Deployment, Service, ConfigMap, Secret, Redis, optional Ingress).
- **B4 expiring links** — `{"url":"…","ttl_seconds":60}` (1..31536000) adds
  `expires_at`; Redis expires the hash itself (`PEXPIREAT`) and `GET /api/links`
  lazily removes expired codes from the ZSET.

## Project layout

```
cmd/snaplink/      main.go (wiring, graceful shutdown), config.go, healthcheck.go
internal/link/     Link, validation, crypto/rand codes, sentinel errors
internal/store/    Store interface, memory.go, redis.go, contract tests
internal/api/      routes, handlers, JSON + error mapping, middleware, metrics
scripts/           check-env.sh, smoke.sh
k8s/               namespace, configmap, secret, redis, app, ingress
charts/snaplink/   Helm chart
```

## AI usage

This reference solution was written with **Claude** (Anthropic) as a pair
programmer, the same way students are allowed to use AI in the exam.

- **Used for:** first drafts of the Dockerfile, compose file, k8s manifests and
  Helm templates; test tables; README wording.
- **Done / reviewed by hand:** the Redis key design, both Lua scripts, the
  error→status mapping, route precedence, and every line of concurrency code.
- **What the AI got wrong (and was fixed):**
  1. The first `Redis.Hit` was `HINCRBY` followed by `HGET`. It looks atomic,
     but `HINCRBY` on a missing key *creates* the hash, so a click after a
     DELETE resurrected a half-empty link (`{clicks: 1}`) and `GET /api/links/{code}`
     failed. The Redis integration test "hit after delete does not resurrect
     the link" caught it; the fix is a Lua script that checks `EXISTS` before
     `HINCRBY` (commit `fix(store): …`).
  2. It proposed `math/rand` for the 6-character codes. Rejected: `math/rand`
     is predictable, so codes could be enumerated; `crypto/rand` with
     `rand.Int` (no modulo bias) is used instead.
- **Rule I followed:** nothing was committed that did not pass `go vet`,
  `go test -race` and `scripts/smoke.sh`, and that I could not explain.
