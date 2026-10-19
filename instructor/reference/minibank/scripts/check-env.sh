#!/usr/bin/env bash
# check-env.sh — verify the tools needed to build and ship MiniBank.
# Prints "✓ <tool> <version>" or "✗ <tool> not found" per tool.
# Exit 0 and "ALL GOOD" when everything is present, else exit 1 and
# "MISSING: a, b".
set -euo pipefail

missing=()

# check <name> <version command...>
check() {
  local name=$1
  shift
  if command -v "$name" >/dev/null 2>&1; then
    local version
    version=$("$@" 2>/dev/null | head -n 1 || true)
    echo "✓ $name ${version:-(version unknown)}"
  else
    echo "✗ $name not found"
    missing+=("$name")
  fi
}

check go go version
check git git --version
check docker docker --version
check kubectl kubectl version --client

# A local cluster: kind OR minikube is enough.
if command -v kind >/dev/null 2>&1; then
  check kind kind version
elif command -v minikube >/dev/null 2>&1; then
  check minikube minikube version --short
else
  echo "✗ kind/minikube not found (install one of them)"
  missing+=("kind or minikube")
fi

# The docker CLI can exist while the daemon is stopped (Docker Desktop not running).
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    echo "✓ docker daemon reachable"
  else
    echo "✗ docker daemon not reachable (start Docker Desktop / sudo systemctl start docker)"
    missing+=("docker daemon")
  fi
fi

if ((${#missing[@]} == 0)); then
  echo "ALL GOOD"
  exit 0
fi

# Join the array with ", ".
joined=$(printf ', %s' "${missing[@]}")
echo "MISSING: ${joined:2}"
exit 1
