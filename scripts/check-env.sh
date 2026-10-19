#!/usr/bin/env bash
# check-env.sh — is this machine ready for the SnapLink build & ship exam?
# Checks go, git, docker, kubectl, kind OR minikube, and the Docker daemon.
# Exit 0 + "ALL GOOD" when everything is there, else exit 1 + "MISSING: a, b".
set -euo pipefail

missing=""

add_missing() {
  if [[ -z $missing ]]; then missing=$1; else missing="$missing, $1"; fi
}

# version <tool> — print a short version string (never fails)
version() {
  case $1 in
    go)       go env GOVERSION 2>/dev/null ;;
    git)      git --version 2>/dev/null | awk '{print $3}' ;;
    docker)   docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' ;;
    kubectl)  kubectl version --client 2>/dev/null | awk 'NR==1 {print $NF}' ;;
    kind)     kind version 2>/dev/null | awk '{print $2}' ;;
    minikube) minikube version --short 2>/dev/null ;;
  esac || true
}

check() {
  local tool=$1
  if command -v "$tool" >/dev/null 2>&1; then
    printf '✓ %s %s\n' "$tool" "$(version "$tool")"
  else
    printf '✗ %s not found\n' "$tool"
    add_missing "$tool"
  fi
}

check go
check git
check docker
check kubectl

# A local cluster tool: kind OR minikube is enough.
if command -v kind >/dev/null 2>&1; then
  check kind
elif command -v minikube >/dev/null 2>&1; then
  check minikube
else
  printf '✗ kind/minikube not found\n'
  add_missing "kind/minikube"
fi

# The docker CLI alone is not enough: the daemon must answer too.
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    printf '✓ docker daemon reachable\n'
  else
    printf '✗ docker daemon not reachable (start Docker Desktop, or: sudo systemctl start docker)\n'
    add_missing "docker daemon"
  fi
fi

if [[ -z $missing ]]; then
  echo "ALL GOOD"
  exit 0
fi
echo "MISSING: $missing"
exit 1
