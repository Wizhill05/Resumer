#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"

if [[ ! -d "$ROOT/frontend" ]]; then
  echo "Could not find frontend folder at: $ROOT/frontend" >&2
  exit 1
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT"
uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "Backend started (PID: $BACKEND_PID)"
echo "Starting frontend..."

cd "$ROOT/frontend"
pnpm run dev
