#!/usr/bin/env bash
# Run the live demo: seed tickets → wait for triage → accuracy summary.
#
# Usage:
#   ./scripts/run-demo.sh          # 50 tickets (~4 min) — Loom recording
#   ./scripts/run-demo.sh smoke    # 3 tickets (~2 min) — practice
#   ./scripts/run-demo.sh check    # preflight only
#
# Before running:
#   1. Terminal 1: ./scripts/dev.sh
#   2. Jira webhook ON → $WEBHOOK_PUBLIC_URL/rest/webhooks/jira (Issue created)
#   3. .env has MODEL, GOOGLE_API_KEY, Jira creds, EVAL_BULK_MODE=1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-full}"
LIMIT=3
EXPECTED=3
if [[ "$MODE" == "full" ]]; then
  LIMIT=""
  EXPECTED=50
elif [[ "$MODE" == "check" ]]; then
  LIMIT=""
  EXPECTED=0
elif [[ "$MODE" != "smoke" ]]; then
  echo "Usage: $0 [full|smoke|check]" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

PORT="${WEBHOOK_PORT:-8000}"
PUBLIC_URL="${WEBHOOK_PUBLIC_URL:-}"
CSV="${EVAL_LIVE_REPORT_PATH:-eval/live_results.csv}"

echo "=== Run demo — preflight ==="
echo "Webhook URL: ${PUBLIC_URL%/}/rest/webhooks/jira"
echo "MODEL: ${MODEL:-MISSING}"
echo "JIRA_PROJECT_KEY: ${JIRA_PROJECT_KEY:-MISSING}"
echo "EVAL_BULK_MODE: ${EVAL_BULK_MODE:-off}"
echo "LLM_MAX_CONCURRENT: ${LLM_MAX_CONCURRENT:-<bulk default>}"
echo

missing=0
for var in MODEL GOOGLE_API_KEY JIRA_DOMAIN JIRA_EMAIL JIRA_API_TOKEN JIRA_PROJECT_KEY WEBHOOK_PUBLIC_URL; do
  if [[ -z "${!var:-}" ]]; then
    echo "MISSING: $var" >&2
    missing=1
  fi
done
if [[ "$missing" -eq 1 ]]; then
  exit 1
fi

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
  echo "Agent not reachable on port ${PORT}." >&2
  echo "Start in another terminal: ./scripts/dev.sh" >&2
  exit 1
fi
echo "Health check: OK (port ${PORT})"
echo

if [[ "$MODE" == "check" ]]; then
  echo "Preflight passed. Enable Jira webhook, then:"
  echo "  ./scripts/run-demo.sh smoke   # practice"
  echo "  ./scripts/run-demo.sh         # full demo"
  exit 0
fi

echo "Seeding tickets (Jira webhook must be enabled for Issue created)."
rm -f "$CSV"
echo "Cleared ${CSV}"
echo

if [[ -n "$LIMIT" ]]; then
  echo "=== Seeding ${LIMIT} eval tickets ==="
  uv run python scripts/jira_eval_tickets.py seed --limit "$LIMIT"
else
  echo "=== Seeding all 50 eval tickets ==="
  uv run python scripts/jira_eval_tickets.py seed
fi

echo
echo "=== Waiting for triage (${EXPECTED} rows in ${CSV}) ==="
echo "Watch Terminal 1 (dev.sh) for QUEUED / START / DONE / ALL DONE logs."
deadline=$((SECONDS + 600))
while (( SECONDS < deadline )); do
  if [[ -f "$CSV" ]]; then
    count=$(($(wc -l < "$CSV") - 1))
    if [[ "$count" -ge "$EXPECTED" ]]; then
      echo "CSV has ${count} rows."
      break
    fi
    echo "  ... ${count}/${EXPECTED} rows"
  fi
  sleep 5
done

count=0
if [[ -f "$CSV" ]]; then
  count=$(($(wc -l < "$CSV") - 1))
fi
if [[ "$count" -lt "$EXPECTED" ]]; then
  echo "Timed out waiting for ${EXPECTED} rows in ${CSV} (got ${count})." >&2
  echo "Check Terminal 1 logs and Jira board." >&2
  exit 1
fi

echo
echo "=== Accuracy summary ==="
uv run python scripts/summarize_live_eval.py --csv "$CSV" --expected "$EXPECTED"

echo
echo "=== Demo complete ==="
