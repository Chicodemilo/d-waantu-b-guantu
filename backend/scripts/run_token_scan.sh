#!/usr/bin/env bash
#
# run_token_scan.sh — Scan Claude transcripts and attribute tokens to tickets.
#
# Usage:
#   ./scripts/run_token_scan.sh --project-id 1
#   ./scripts/run_token_scan.sh --project-id 1 --dry-run
#   ./scripts/run_token_scan.sh --project-id 1 --force
#
# Environment variables (all optional):
#   LAT_API_URL              — API base URL (default: http://localhost:8000)
#   LAT_DEFAULT_PROJECT_ID   — fallback project ID (default: 1)
#   LAT_TOKEN_SANITY_CAP     — max tokens per transcript (default: 10000000)
#   LAT_TRANSCRIPT_DIR       — override transcript scan directory
#   LAT_TOKEN_STATE_FILE     — state file path (default: /tmp/lat_token_attribution_state.json)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$BACKEND_DIR")"

API_BASE="${LAT_API_URL:-http://localhost:8000}"
PROJECT_ID=""
DRY_RUN=""
FORCE=""
EXTRA_ARGS=()

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-id)   PROJECT_ID="$2"; shift 2 ;;
        --dry-run)      DRY_RUN="--dry-run"; shift ;;
        --force)        FORCE="--force"; shift ;;
        --help|-h)
            head -11 "$0" | tail -9
            exit 0
            ;;
        *) EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="${LAT_DEFAULT_PROJECT_ID:-1}"
fi

# Activate venv if not already active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "$BACKEND_DIR/.venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "$BACKEND_DIR/.venv/bin/activate"
    else
        echo "ERROR: No virtualenv found at $BACKEND_DIR/.venv" >&2
        exit 1
    fi
fi

# Load .env for DB/API settings
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

echo ""
echo "=== Token Attribution Scan ==="
echo "  Project ID: $PROJECT_ID"
echo "  API:        $API_BASE"
if [[ -n "$DRY_RUN" ]]; then
    echo "  Mode:       DRY RUN"
fi
echo ""

# Run the scanner — capture output and the JSON summary on the last line
cd "$BACKEND_DIR"
OUTPUT=$(python scripts/attribute_tokens.py \
    --project-id "$PROJECT_ID" \
    $DRY_RUN \
    $FORCE \
    "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" 2>&1) || true

echo "$OUTPUT"

# Extract the JSON summary (last non-empty line)
SUMMARY_JSON=$(echo "$OUTPUT" | grep '^{' | tail -1)

if [[ -z "$SUMMARY_JSON" ]]; then
    echo "WARNING: No summary JSON produced"
    exit 0
fi

# Parse summary for the alert
ATTRIBUTED=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('attributed',0))")
TOTAL_TOKENS=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('total_tokens',0))")
PROCESSED=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('processed',0))")
SKIPPED_NO_TICKET=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('skipped_no_ticket',0))")

# Post summary alert (skip if dry run or nothing processed)
if [[ -z "$DRY_RUN" && "$PROCESSED" -gt 0 ]]; then
    ALERT_BODY="Scanned $PROCESSED teammate transcript(s). Attributed $TOTAL_TOKENS tokens across $ATTRIBUTED session(s)."
    if [[ "$SKIPPED_NO_TICKET" -gt 0 ]]; then
        ALERT_BODY="$ALERT_BODY $SKIPPED_NO_TICKET session(s) had no matching ticket."
    fi

    # Build details from the summary
    DETAILS=$(echo "$SUMMARY_JSON" | python3 -c "
import sys, json
s = json.load(sys.stdin)
for d in s.get('details', []):
    print(f\"  {d['agent']} → {d['ticket_key']}: {d['tokens']:,} tokens [{d['status']}]\")
")
    if [[ -n "$DETAILS" ]]; then
        ALERT_BODY="$ALERT_BODY

$DETAILS"
    fi

    # POST alert
    ALERT_PAYLOAD=$(python3 -c "
import json
print(json.dumps({
    'project_id': int('$PROJECT_ID'),
    'raised_by_agent_id': 5,
    'ticket_id': None,
    'title': 'Token scan complete: $TOTAL_TOKENS tokens attributed',
    'body': '''$ALERT_BODY''',
    'severity': 'info',
}))
")

    curl -s -X POST "$API_BASE/api/alerts" \
        -H "Content-Type: application/json" \
        -d "$ALERT_PAYLOAD" > /dev/null 2>&1 || true

    echo ""
    echo "=== Summary alert posted ==="
fi

echo ""
echo "Done."
