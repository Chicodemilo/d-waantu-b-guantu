#!/usr/bin/env bash
# Path: scripts/run_standards_audit.sh
# Created: 2026-08-11
# Last Modified: 2026-08-11 (DWB-015)
# Purpose: Run a standards audit over a PR/diff. Thin entrypoint that resolves
#   the repo root, loads .env, ensures a Python 3 interpreter, and hands off to
#   scripts/standards_audit.py (the runner). Kept as a shell wrapper so the
#   audit can be invoked identically from a server, a git hook, or a laptop.
#
# What it does:
#   Gathers a diff (branch vs merge-base master, an explicit range, or the
#   staged changes), spawns a FRESH single-purpose headless auditor whose ONLY
#   context is the global standards sheet + the diff (never team/Archie context),
#   parses the auditor's strict JSON, prints a uniform human scorecard, and POSTs
#   the audit to the DWB standards-audit API.
#
# How to run (from anywhere; paths resolve to the repo root):
#   scripts/run_standards_audit.sh --project-id 5 --branch my-feature
#   scripts/run_standards_audit.sh --project-id 5 --range abc123..def456 --ticket-id 164
#   scripts/run_standards_audit.sh --project-id 5 --staged --dry-run
#
# Flags (parsed by standards_audit.py — run with --help for the full list):
#   --project-id N        (required) DWB project id
#   --branch <name>       diff the branch against merge-base with master
#   --range <a..b>        diff an explicit git range
#   --staged              diff the staged changes
#   --ticket-id N         (optional) associate the audit with a ticket
#   --sprint-id N         (optional) associate the audit with a sprint
#   --dry-run             print the payload + scorecard, do NOT POST
#
# Config: read from .env only (STANDARDS_AUDIT_API_BASE / VITE_API_BASE_URL,
#   STANDARDS_AUDIT_MODEL). No hard-coded hosts, keys, or model names here.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

# Prefer a repo virtualenv python if present, else system python3.
if [[ -x "$repo_root/backend/.venv/bin/python" ]]; then
  python_bin="$repo_root/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
else
  echo "run_standards_audit.sh: no python3 interpreter found on PATH" >&2
  exit 1
fi

exec "$python_bin" "$script_dir/standards_audit.py" --repo-root "$repo_root" "$@"
