#!/usr/bin/env bash
# Start FastAPI locally and expose it via ngrok using WEBHOOK_PUBLIC_URL from .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and configure WEBHOOK_PUBLIC_URL." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

PORT="${WEBHOOK_PORT:-8000}"
PUBLIC_URL="${WEBHOOK_PUBLIC_URL:-}"

if [[ -z "$PUBLIC_URL" ]]; then
  echo "Set WEBHOOK_PUBLIC_URL in .env (ngrok free static domain)." >&2
  echo "See README → Local dev with ngrok." >&2
  exit 1
fi

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok not found. Install with: brew install ngrok/ngrok/ngrok" >&2
  exit 1
fi

echo "Jira webhook URL: ${PUBLIC_URL%/}/webhook/jira"
echo "Starting uvicorn on 0.0.0.0:${PORT} ..."

uv run uvicorn serve:app --host 0.0.0.0 --port "$PORT" &
UVICORN_PID=$!

cleanup() {
  kill "$UVICORN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 1
echo "Starting ngrok tunnel → ${PUBLIC_URL} ..."
exec ngrok http --url="$PUBLIC_URL" "$PORT"
