#!/usr/bin/env bash
# Start FastAPI locally and expose it via ngrok using WEBHOOK_PUBLIC_URL from .env.
#
# Terminal 1 shows agent logs (QUEUED/START/DONE, LLM metrics, errors).
# ngrok runs in the background — open http://127.0.0.1:4040 for the request dashboard.
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
  echo "See README → Running." >&2
  exit 1
fi

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok not found. Install with: brew install ngrok/ngrok/ngrok" >&2
  exit 1
fi

LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"
AGENT_LOG="${LOG_DIR}/agent.log"

cleanup() {
  kill "$NGROK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Jira webhook URL: ${PUBLIC_URL%/}/rest/webhooks/jira"
echo "ngrok dashboard:  http://127.0.0.1:4040"
echo "Log file:         ${AGENT_LOG}"
echo
echo "Starting ngrok tunnel → ${PUBLIC_URL} ..."
ngrok http --url="$PUBLIC_URL" "$PORT" >/dev/null 2>&1 &
NGROK_PID=$!

sleep 2
echo "Starting uvicorn on 0.0.0.0:${PORT} ..."
echo "--- agent logs ---"

uv run uvicorn serve:app --host 0.0.0.0 --port "$PORT" 2>&1 | tee -a "$AGENT_LOG"
