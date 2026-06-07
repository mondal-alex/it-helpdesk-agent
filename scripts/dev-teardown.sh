#!/usr/bin/env bash
# Stop local dev processes from scripts/dev.sh (uvicorn on WEBHOOK_PORT, ngrok tunnel).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT=8000
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
  PORT="${WEBHOOK_PORT:-8000}"
fi

stopped=0

pids=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [[ -n "$pids" ]]; then
  echo "Stopping process(es) on port ${PORT}: $(echo "$pids" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  stopped=1
fi

while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  echo "Stopping ngrok (pid ${pid})"
  kill "$pid" 2>/dev/null || true
  stopped=1
done < <(pgrep -f "ngrok http.*${PORT}" 2>/dev/null || true)

if [[ "$stopped" -eq 0 ]]; then
  echo "Nothing to stop — port ${PORT} is already free."
  exit 0
fi

sleep 0.5
remaining=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [[ -n "$remaining" ]]; then
  echo "Port ${PORT} still in use; sending SIGKILL..." >&2
  # shellcheck disable=SC2086
  kill -9 $remaining 2>/dev/null || true
fi

echo "Port ${PORT} is free."
