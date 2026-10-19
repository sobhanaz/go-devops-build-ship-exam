#!/usr/bin/env bash
# smoke.sh — black-box smoke test for a running SnapLink.
#   usage: scripts/smoke.sh [BASE_URL]        (default http://localhost:8080)
# Works against `go run`, docker compose and a kubectl port-forward.
# Never follows redirects (no curl -L): we want to SEE the 302.
set -euo pipefail

BASE_URL=${1:-http://localhost:8080}
BASE_URL=${BASE_URL%/}

pass=0
fail=0
STATUS=""
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# req METHOD PATH [JSON] — sets STATUS; body in $TMP/body, headers in $TMP/headers
req() {
  local method=$1 path=$2 data=${3:-}
  local args=(-s -o "$TMP/body" -D "$TMP/headers" -w '%{http_code}' --max-time 5 -X "$method")
  if [[ -n $data ]]; then
    args+=(-H 'Content-Type: application/json' --data "$data")
  fi
  STATUS=$(curl "${args[@]}" "$BASE_URL$path") || STATUS="000"
}

ok()  { echo "PASS $1"; pass=$((pass + 1)); }
bad() { echo "FAIL $1 (expected $2, got $3)"; fail=$((fail + 1)); }

# expect NAME STATUS — compare the last response status
expect() {
  if [[ $STATUS == "$2" ]]; then ok "$1"; else bad "$1" "$2" "$STATUS"; fi
}

# field NAME — top-level string/number field of the last JSON body (jq or sed)
field() {
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg k "$1" '.[$k] // empty' "$TMP/body" 2>/dev/null || true
  else
    sed -n "s/.*\"$1\":\"\{0,1\}\([^\",}]*\).*/\1/p" "$TMP/body" | head -n 1
  fi
}

header() {
  grep -i "^$1:" "$TMP/headers" | head -n 1 | cut -d' ' -f2- | tr -d '\r' || true
}

# Give a freshly started stack a few seconds to come up.
for _ in $(seq 1 15); do
  req GET /healthz
  [[ $STATUS == 200 ]] && break
  sleep 1
done

echo "SnapLink smoke test against $BASE_URL"

req GET /healthz
expect "healthz" 200

req GET /readyz
expect "readyz" 200

target="https://example.com/smoke/$(date +%s)-$RANDOM"
req POST /api/links "{\"url\":\"$target\"}"
expect "create link" 201
code=$(field code)
if [[ -n $code ]]; then ok "capture code ($code)"; else bad "capture code" "a code" "nothing"; code="missing"; fi

req GET "/$code"
expect "redirect" 302
location=$(header location)
if [[ $location == "$target" ]]; then ok "redirect location"; else bad "redirect location" "$target" "${location:-none}"; fi

req GET "/api/links/$code"
expect "get link" 200
clicks=$(field clicks)
if [[ ${clicks:-0} =~ ^[0-9]+$ ]] && ((clicks >= 1)); then ok "clicks counted ($clicks)"; else bad "clicks counted" ">= 1" "${clicks:-none}"; fi

req GET /api/links
expect "list links" 200

custom="smoke-$RANDOM$RANDOM"
req POST /api/links "{\"url\":\"$target\",\"code\":\"$custom\"}"
expect "create custom code" 201
req POST /api/links "{\"url\":\"$target\",\"code\":\"$custom\"}"
expect "duplicate custom code" 409

req POST /api/links '{"url":"ftp://example.com"}'
expect "invalid url" 400

req GET "/nope$RANDOM$RANDOM"
expect "unknown code" 404

req DELETE "/api/links/$code"
expect "delete link" 204
req GET "/$code"
expect "deleted link is gone" 404
req DELETE "/api/links/$custom" # cleanup, not a check

echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
