# MiniBank

![CI](https://github.com/<your-user>/minibank/actions/workflows/ci.yml/badge.svg)

A small ledger service written in Go: accounts, deposits, withdrawals,
**atomic transfers** and per-account history, stored in PostgreSQL. It never
loses money under concurrent requests. Shipped with Bash scripts, Docker,
Docker Compose, GitHub Actions and Kubernetes (plus Prometheus metrics, an
Ingress and a Helm chart as bonuses).

Design notes: [DECISIONS.md](DECISIONS.md).

## Architecture

```
            HTTP :8080 (JSON)
                  │
┌─────────────────▼──────────────────────────────────────────────┐
│ cmd/minibank   config (env) · store selection · graceful stop   │
├────────────────────────────────────────────────────────────────┤
│ internal/api   middleware: slog JSON log → metrics → recover    │
│                ServeMux "GET /accounts/{id}" … → handlers       │
│                decodeJSON · writeJSON · statusFor(err)          │
├────────────────────────────────────────────────────────────────┤
│ internal/store  Store interface                                 │
│        ┌──────────────────────┐   ┌──────────────────────────┐  │
│        │ Memory (RWMutex)     │   │ Postgres (pgx pool)      │  │
│        │ STORE=memory         │   │ STORE=postgres           │  │
│        └──────────────────────┘   └────────────┬─────────────┘  │
├────────────────────────────────────────────────┼───────────────┤
│ internal/bank  Account · Transaction · rules · sentinel errors  │
└────────────────────────────────────────────────┼───────────────┘
                                                 ▼
                                    PostgreSQL 16 (accounts, transactions)
```

Kubernetes (namespace `minibank`):

```
 kubectl port-forward / Ingress minibank.local
              │
     Service minibank :80 ──► Deployment minibank (2 pods, :8080)
                                   │  envFrom ConfigMap, DATABASE_URL from Secret
                                   ▼
     Service postgres :5432 ──► Deployment postgres (1 pod) ──► PVC postgres-data
```

## API

| Method & path | Body | Success |
|---|---|---|
| `GET /healthz` | – | 200 `{"status":"ok"}` (never touches the DB) |
| `GET /readyz` | – | 200 `{"status":"ready"}` / 503 `{"status":"not ready"}` |
| `POST /accounts` | `{"owner":"Sara"}` | 201 Account |
| `GET /accounts` | – | 200 `[Account…]` sorted by id |
| `GET /accounts/{id}` | – | 200 Account |
| `POST /accounts/{id}/deposit` | `{"amount":500}` | 200 Account |
| `POST /accounts/{id}/withdraw` | `{"amount":200}` | 200 Account · 409 insufficient funds |
| `POST /transfers` | `{"from":1,"to":2,"amount":300}` | 201 Transaction |
| `GET /accounts/{id}/transactions` | – | 200 `[Transaction…]` oldest first |
| `GET /metrics` | – | Prometheus text format |

Errors are `{"error":"<message>"}` with 400 → 404 → 409 precedence.

```bash
curl -s -X POST localhost:8080/accounts -d '{"owner":"Sara"}'
curl -s -X POST localhost:8080/accounts/1/deposit -d '{"amount":1000}'
curl -s -X POST localhost:8080/transfers -d '{"from":1,"to":2,"amount":300}'
curl -s localhost:8080/accounts/1/transactions
```

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `STORE` | `postgres` | `postgres` or `memory` |
| `DATABASE_URL` | – (required when `STORE=postgres`) | e.g. `postgres://minibank:secret@localhost:5432/minibank?sslmode=disable` |
| `MINIBANK_TEST_DATABASE_URL` | – | only for tests: enables the Postgres integration tests |

The app exits with one clear log line when the configuration is invalid.

## Run it

### 1. Locally, in-memory (no database)

```bash
STORE=memory go run ./cmd/minibank
scripts/smoke.sh http://localhost:8080
```

### 2. Docker Compose (app + PostgreSQL)

```bash
cp .env.example .env          # edit POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps             # both services "healthy"
scripts/smoke.sh http://localhost:8080
docker compose down           # data stays in the named volume "pgdata"
```

The database port is not published; only the app can reach it.

**The image.** Multi-stage build: `golang:1.25-alpine` compiles a static
binary (`CGO_ENABLED=0`, `-ldflags "-s -w"`), the runtime stage is `FROM scratch`
with only that binary, running as uid/gid `65532` (about 13 MB in total).
scratch is used instead of `gcr.io/distroless` because gcr.io is often
unreachable from Iran. scratch has no shell and no curl, so the Docker
`HEALTHCHECK` and the compose healthcheck call the binary itself:
`/minibank -healthcheck`.

### 3. Kubernetes on kind

```bash
kind create cluster --name minibank
docker build -t minibank:v1 .
kind load docker-image minibank:v1 --name minibank
kubectl apply -f k8s/
kubectl -n minibank rollout status deploy/postgres
kubectl -n minibank rollout status deploy/minibank
kubectl -n minibank port-forward svc/minibank 8080:80
scripts/smoke.sh http://localhost:8080        # in a second terminal
```

minikube: `minikube image load minibank:v1` instead of `kind load`.

**Probes.** Three different questions:

| Probe | Path | Question | On failure |
|---|---|---|---|
| `startupProbe` | `/healthz` every 2 s, 30 tries | has the process finished starting? | restart after ~60 s |
| `livenessProbe` | `/healthz` | is the process still alive? (never touches the DB) | restart the container |
| `readinessProbe` | `/readyz` (pings Postgres, 2 s timeout; probe timeout 3 s) | can it serve traffic now? | removed from the Service, not restarted |

The app connects to Postgres (retrying) *before* it starts listening. On a
fresh `kubectl apply -f k8s/` Postgres often needs 30–60 s, and without a
startup probe the liveness probe killed the app pods while they were still
waiting for the database (CrashLoopBackOff). The startup probe gives them up
to 60 s; liveness only starts once it has succeeded. A later database outage
only makes `/readyz` fail: the pods stop receiving traffic but keep running.

**PVC vs emptyDir.** Postgres uses a 1 Gi PersistentVolumeClaim, so accounts
survive a postgres pod restart. An `emptyDir` would be simpler but is deleted
with the pod: every restart would wipe the bank. The PVC is ReadWriteOnce,
therefore postgres runs as 1 replica with the `Recreate` strategy.

**Why not STORE=memory in Kubernetes?** With 2 replicas each pod would have
its own private bank and requests would see different balances.

#### Ingress (bonus B2)

```bash
cat <<'EOF' | kind create cluster --name minibank --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
EOF
kubectl apply -f https://kind.sigs.k8s.io/examples/ingress/deploy-ingress-nginx.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod -l app.kubernetes.io/component=controller --timeout=120s
echo "127.0.0.1 minibank.local" | sudo tee -a /etc/hosts
kubectl apply -f k8s/
scripts/smoke.sh http://minibank.local
```

#### Helm (bonus B3)

```bash
kubectl delete namespace minibank --ignore-not-found   # do not mix with k8s/
helm install minibank charts/minibank -n minibank --create-namespace \
  --set postgres.password="$(openssl rand -hex 16)"
kubectl -n minibank port-forward svc/minibank 8080:80
helm upgrade minibank charts/minibank -n minibank --reuse-values --set replicaCount=3
```

### Metrics (bonus B1)

`GET /metrics`: `http_requests_total{method,path,status}` (path is the route
pattern such as `/accounts/{id}`, never the raw URL), the
`http_request_duration_seconds` histogram and
`minibank_transfers_total{result="ok|insufficient_funds|error"}`.

## Tests

```bash
gofmt -l . && go vet ./... && go test -race -count=1 ./...   # no DB needed

# Postgres integration tests (skipped unless the variable is set):
MINIBANK_TEST_DATABASE_URL='postgres://minibank:secret@localhost:5432/minibank?sslmode=disable' \
  go test -race -count=1 ./internal/store/
```

- table-driven tests for validation and for every store error (`errors.Is`)
- the same store contract tests run against Memory and Postgres
- storms: 100 parallel deposits, 50 competing transfers (exactly 33 succeed),
  200 bidirectional transfers (no deadlock, money conserved)
- `httptest` tests for every endpoint, panic recovery, readiness with the DB down, metrics

Scripts: `scripts/check-env.sh` (are go, git, docker, kubectl, kind/minikube
installed and is the Docker daemon up?) and `scripts/smoke.sh [BASE_URL]`.

## AI usage

- **Tool:** Claude (chat + coding agent). This reference solution was written
  with Claude and reviewed by the instructor.
- **Used for:** boilerplate (JSON helpers, handler skeletons), first drafts of
  the Dockerfile, compose file, Kubernetes manifests and Helm templates, and
  as a reviewer that tried to break the concurrency code.
- **What the AI got wrong and I fixed:**
  1. The first transfer draft was read-check-write: `SELECT balance`, check in
     Go, then `UPDATE accounts SET balance = $1` with the computed value, without
     a transaction. Under 50 parallel transfers that lets several requests see
     the same old balance (lost updates). Fixed with ONE SQL transaction,
     `SELECT … FOR UPDATE` and relative updates (`balance = balance - $1`).
  2. It then locked the rows in from→to order, which deadlocks when A→B and
     B→A run at the same time (Postgres 40P01 → HTTP 500). Fixed by locking in
     ascending id order (plus a retry on 40P01/40001 as a safety net).
  3. It suggested `r.Pattern` for the metrics label, which only exists from
     Go 1.23; the module targets Go 1.22, so the label comes from
     `ServeMux.Handler` instead.
- **What I did not delegate:** the lock-order reasoning, the error precedence,
  and the readiness vs liveness split — I can explain each line of those.
