#!/usr/bin/env bash
# Path: backend/scripts/run_tests.sh
# File: run_tests.sh
# Created: 2026-03-27
# Purpose: Run backend pytest suite and optionally POST results to the LAT API
# Caller: Manual CLI, Claude Code hooks
# Callees: pytest, curl → POST /api/test-results
# Data In: CLI args (--post, --project-id, --triggered-by, --context, --url)
# Data Out: Pytest output + JSON report; optional HTTP POST to API
# Last Modified: 2026-03-29
#
# run_tests.sh — Run the backend pytest suite and optionally POST results to the API.
#
# Usage:
#   ./scripts/run_tests.sh                          # run tests, print summary
#   ./scripts/run_tests.sh --post --project-id 1    # run tests and POST results to API
#   ./scripts/run_tests.sh --post --project-id 1 --triggered-by "agent:tester"
#   ./scripts/run_tests.sh --post --project-id 1 --context "after DWB-034 sprint name fix"
#   ./scripts/run_tests.sh --url http://localhost:8000 --post --project-id 1
#
# When to run:
#   - Manually from CLI during development
#   - After completing a task/ticket
#   - As a hook target (e.g., Claude Code post-task hook)
#   - After a sprint of work to capture a snapshot

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$BACKEND_DIR")"

# Environment variables (all optional, sensible defaults):
#   LAT_API_URL         — API base URL (default: http://localhost:8000)
#   LAT_PYTEST_REPORT   — path for JSON test report (default: /tmp/lat_pytest_report.json)
#   LAT_PYTEST_OUTPUT   — path for raw pytest output (default: $PYTEST_OUTPUT)
#   LAT_POST_RESPONSE   — path for POST response body (default: $POST_RESPONSE)

# Defaults
POST_RESULTS=false
API_BASE="${LAT_API_URL:-http://localhost:8000}"
JSON_REPORT="${LAT_PYTEST_REPORT:-/tmp/lat_pytest_report.json}"
PYTEST_OUTPUT="${LAT_PYTEST_OUTPUT:-/tmp/lat_pytest_output.txt}"
POST_RESPONSE="${LAT_POST_RESPONSE:-/tmp/lat_post_response.txt}"
PROJECT_ID=""
TRIGGERED_BY="manual"
TRIGGERED_CONTEXT=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --post)         POST_RESULTS=true; shift ;;
        --url)          API_BASE="$2"; shift 2 ;;
        --project-id)   PROJECT_ID="$2"; shift 2 ;;
        --triggered-by) TRIGGERED_BY="$2"; shift 2 ;;
        --context)      TRIGGERED_CONTEXT="$2"; shift 2 ;;
        --help|-h)
            head -15 "$0" | tail -13
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ "$POST_RESULTS" == "true" && -z "$PROJECT_ID" ]]; then
    echo "ERROR: --project-id is required when using --post" >&2
    exit 1
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

# Load .env for DB connection settings
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

echo "=== Running backend tests ==="

# Run pytest with JSON report
cd "$BACKEND_DIR"
PYTEST_EXIT=0
python -m pytest tests/ \
    --json-report \
    --json-report-file="$JSON_REPORT" \
    -v \
    2>&1 | tee $PYTEST_OUTPUT || PYTEST_EXIT=$?

echo ""
echo "=== Pytest exit code: $PYTEST_EXIT ==="

# Parse results from JSON report
if [[ ! -f "$JSON_REPORT" ]]; then
    echo "ERROR: JSON report not generated at $JSON_REPORT" >&2
    exit 1
fi

# Extract summary using python (available since we're in a venv)
SUMMARY=$(python3 -c "
import json, sys

with open('$JSON_REPORT') as f:
    report = json.load(f)

s = report.get('summary', {})
print(f\"Passed: {s.get('passed', 0)}\")
print(f\"Failed: {s.get('failed', 0)}\")
print(f\"Errors: {s.get('error', 0)}\")
print(f\"Skipped: {s.get('skipped', 0)}\")
print(f\"Total:  {s.get('total', 0)}\")
print(f\"Duration: {report.get('duration', 0):.2f}s\")
")

echo ""
echo "=== Test Summary ==="
echo "$SUMMARY"

# POST results to API if requested
if [[ "$POST_RESULTS" == "true" ]]; then
    echo ""
    echo "=== Posting results to $API_BASE/api/test-results ==="

    # Build the payload matching TestResultCreate schema
    PAYLOAD=$(python3 -c "
import json, sys
from datetime import datetime, timezone

with open('$JSON_REPORT') as f:
    report = json.load(f)

s = report.get('summary', {})
tests = report.get('tests', [])

# Determine overall status (API expects: passed, failed, error)
if s.get('error', 0) > 0:
    status = 'error'
elif s.get('failed', 0) > 0:
    status = 'failed'
else:
    status = 'passed'

# Build per-test details as JSON string for the 'details' text field
test_details = []
for t in tests:
    # pytest-json-report stores durations in setup/call/teardown phases, not top-level
    dur = sum(
        t.get(phase, {}).get('duration', 0) or 0
        for phase in ('setup', 'call', 'teardown')
    )
    test_details.append({
        'nodeid': t.get('nodeid', ''),
        'outcome': t.get('outcome', 'unknown'),
        'duration': round(dur, 4),
    })

details_obj = {
    'tests': test_details,
    'raw_output_tail': open('$PYTEST_OUTPUT').read()[-4000:],
}

payload = {
    'project_id': int('$PROJECT_ID'),
    'suite': 'backend',
    'status': status,
    'total_tests': s.get('total', 0),
    'passed': s.get('passed', 0),
    'failed': s.get('failed', 0),
    'skipped': s.get('skipped', 0),
    'duration_seconds': round(report.get('duration', 0), 3),
    'details': json.dumps(details_obj),
    'triggered_by': '$TRIGGERED_BY',
}

context = '$TRIGGERED_CONTEXT'
if context:
    payload['triggered_context'] = context

print(json.dumps(payload))
")

    HTTP_CODE=$(curl -s -o $POST_RESPONSE -w "%{http_code}" \
        -X POST "$API_BASE/api/test-results" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD")

    if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 300 ]]; then
        echo "Posted successfully (HTTP $HTTP_CODE)"
        cat $POST_RESPONSE
        echo ""
    else
        echo "WARNING: POST failed with HTTP $HTTP_CODE" >&2
        cat $POST_RESPONSE >&2
        echo "" >&2
    fi
fi

# Exit with pytest's exit code
exit $PYTEST_EXIT
