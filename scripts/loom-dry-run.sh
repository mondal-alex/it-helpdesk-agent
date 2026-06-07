#!/usr/bin/env bash
# End-to-end practice run for the Loom demo (webhook → triage → live CSV → accuracy check).
#
# Usage:
#   ./scripts/loom-dry-run.sh smoke     # 3 tickets (~2 min) — practice flow
#   ./scripts/loom-dry-run.sh full      # 50 tickets (~4 min) — record this for Loom
#   ./scripts/loom-dry-run.sh check     # preflight only, no seeding
#
# Before running:
#   1. Jira webhook ON → $WEBHOOK_PUBLIC_URL/rest/webhooks/jira (Issue created)
#   2. .env has MODEL=google_genai:..., GOOGLE_API_KEY, Jira creds, EVAL_BULK_MODE=1
#   3. Remove explicit LLM_MAX_CONCURRENT=2 if present (bulk mode uses 12)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-smoke}"
LIMIT=3
EXPECTED=3
if [[ "$MODE" == "full" ]]; then
  LIMIT=""
  EXPECTED=50
elif [[ "$MODE" == "check" ]]; then
  LIMIT=""
  EXPECTED=0
elif [[ "$MODE" != "smoke" ]]; then
  echo "Usage: $0 {smoke|full|check}" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

PORT="${WEBHOOK_PORT:-8000}"
PUBLIC_URL="${WEBHOOK_PUBLIC_URL:-}"
CSV="${EVAL_LIVE_REPORT_PATH:-eval/live_results.csv}"

echo "=== Loom dry-run preflight ==="
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
  echo "Preflight passed. Start ./scripts/dev.sh, enable Jira webhook, then:"
  echo "  ./scripts/loom-dry-run.sh smoke   # practice"
  echo "  ./scripts/loom-dry-run.sh full    # Loom recording"
  exit 0
fi

echo "=== Confirm Jira webhook is ENABLED (Issue created) ==="
echo "Press Enter to continue or Ctrl-C to abort..."
read -r _

rm -f "$CSV"
echo "Cleared ${CSV}"
echo

if [[ -n "$LIMIT" ]]; then
  echo "=== Seeding ${LIMIT} eval tickets (webhook will triage each) ==="
  uv run python scripts/jira_eval_tickets.py seed --limit "$LIMIT"
else
  echo "=== Seeding all 50 eval tickets ==="
  uv run python scripts/jira_eval_tickets.py seed
fi

echo
echo "=== Waiting for triage to finish (${EXPECTED} rows in ${CSV}) ==="
echo "Watch Terminal 1 for QUEUED / START / DONE / ALL DONE logs."
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

if [[ ! -f "$CSV" ]] || [[ "$(($(wc -l < "$CSV") - 1))" -lt "$EXPECTED" ]]; then
  echo "Timed out waiting for ${EXPECTED} rows in ${CSV}." >&2
  echo "Check Terminal 1 logs and Jira board." >&2
  exit 1
fi

echo
echo "=== Accuracy summary ==="
uv run python scripts/summarize_live_eval.py --csv "$CSV" --expected "$EXPECTED"

echo
echo "=== Loom checklist ==="
echo "  [ ] Terminal 1: dev.sh running, progress logs visible"
echo "  [ ] Terminal 2: seed command + summarize_live_eval PASS"
echo "  [ ] Jira board: tickets moving Under Agent Review → Resolved / Needs Manual Review"
echo "  [ ] Open one RESOLVED ticket: comment with Action + Citation"
echo "  [ ] Open one DEFER ticket: comment with Action + Reason code"
echo "  [ ] Mention: architecture, grounding Gate 1, production hardening"
