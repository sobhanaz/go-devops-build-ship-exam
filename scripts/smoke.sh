#!/usr/bin/env bash
# smoke.sh — end-to-end smoke test of a running MiniBank.
#
#   scripts/smoke.sh                        # http://localhost:8080
#   scripts/smoke.sh http://localhost:18081
#
# Works against `go run`, docker compose and a kubectl port-forward. It only
# creates new accounts (unique owner names) and captures their ids from the
# responses, so it can run any number of times against the same database.
set -euo pipefail

BASE_URL=${1:-http://localhost:8080}
BASE_URL=${BASE_URL%/}

passed=0
failed=0
body_file=$(mktemp)
trap 'rm -f "$body_file"' EXIT

# request METHOD PATH [JSON_BODY] → sets $status and $body
request() {
  local method=$1 path=$2 data=${3:-}
  local args=(-s -o "$body_file" -w '%{http_code}' --max-time 5 -X "$method")
  if [[ -n $data ]]; then
    args+=(-H 'Content-Type: application/json' -d "$data")
  fi
  # A refused connection must count as a failed check, not abort the script.
  status=$(curl "${args[@]}" "$BASE_URL$path") || status="000"
  body=$(cat "$body_file")
}

# expect NAME WANT_STATUS → PASS/FAIL line
expect() {
  local name=$1 want=$2
  if [[ $status == "$want" ]]; then
    echo "PASS $name"
    passed=$((passed + 1))
  else
    echo "FAIL $name (expected $want, got $status)"
    failed=$((failed + 1))
  fi
}

# json_field FIELD → value of a top-level numeric/string field of $body
json_field() {
  if command -v jq >/dev/null 2>&1; then
    jq -r ".$1 // empty" <<<"$body"
  else
    sed -n "s/.*\"$1\":\"\{0,1\}\([^,\"}]*\).*/\1/p" <<<"$body"
  fi
}

run_id="$(date +%s)-$$"

request GET /healthz
expect "healthz" 200

request GET /readyz
expect "readyz" 200

request POST /accounts "{\"owner\":\"smoke-alice-$run_id\"}"
expect "create account alice" 201
alice=$(json_field id)

request POST /accounts "{\"owner\":\"smoke-bob-$run_id\"}"
expect "create account bob" 201
bob=$(json_field id)

if [[ -z $alice || -z $bob ]]; then
  echo "FAIL capture account ids (got alice='$alice' bob='$bob')"
  failed=$((failed + 1))
  alice=${alice:-0} bob=${bob:-0}
fi

request POST "/accounts/$alice/deposit" '{"amount":1000}'
expect "deposit 1000" 200

request POST /accounts "{\"owner\":\"x\"}"
expect "invalid owner rejected" 400

request POST "/accounts/$alice/deposit" '{"amount":0}'
expect "invalid amount rejected" 400

request POST /transfers "{\"from\":$alice,\"to\":$bob,\"amount\":300}"
expect "transfer 300" 201

request POST "/accounts/$bob/withdraw" '{"amount":1000000}'
expect "withdraw too much" 409

request GET "/accounts/$bob"
expect "get account bob" 200
balance=$(json_field balance)
if [[ $balance == "300" ]]; then
  echo "PASS bob balance is 300"
  passed=$((passed + 1))
else
  echo "FAIL bob balance (expected 300, got ${balance:-nothing})"
  failed=$((failed + 1))
fi

request GET "/accounts/$alice/transactions"
expect "list transactions" 200

# Unknown id: far above every id that exists right now.
request GET /accounts
last_id=$(grep -o '"id":[0-9]*' <<<"$body" | tail -n 1 | cut -d: -f2 || true)
request GET "/accounts/$(( ${last_id:-0} + 1000000 ))"
expect "unknown account" 404

echo "$passed passed, $failed failed"
((failed == 0))
