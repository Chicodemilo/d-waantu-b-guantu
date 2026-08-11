#!/usr/bin/env python3
# Path: scripts/standards_audit.py
# File: standards_audit.py
# Created: 2026-08-11
# Purpose: Standards-audit runner. Gathers a diff, spawns a FRESH headless
#   auditor (claude -p) whose ONLY context is the global coding-standards sheet
#   + the diff, validates the auditor's strict JSON, prints a uniform human
#   scorecard, and POSTs the audit to the DWB standards-audit API (DWB-014).
# Caller: scripts/run_standards_audit.sh (thin wrapper); may also run directly.
# Callees: git (diff gathering), `claude -p` (the fresh auditor), the DWB API
#   POST /api/standards-audits.
# Data In: CLI flags (--project-id, one of --branch/--range/--staged, optional
#   --ticket-id/--sprint-id/--dry-run). Config from .env only.
# Data Out: Exit 0 + a stored audit (or, with --dry-run, the payload printed).
#   Non-zero exit + a clear message on malformed auditor output or API failure.
# Last Modified: 2026-08-11 (DWB-015)
#
# Design note: the auditor is deliberately context-starved. It runs from a
#   throwaway temp directory (so it cannot auto-load this repo's CLAUDE.md or any
#   team/Archie context) and its prompt contains ONLY the standards sheet + the
#   diff + output instructions. That is the whole point — fresh eyes that cannot
#   rubber-stamp. See the ONE-PLACE endpoint mapping in post_audit()/build_payload().

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

# --- Constants pinned by the DWB contract (DWB-014 / ticket 163) --------------
AUDIT_ENDPOINT_PATH = "/standards-audits"   # appended to the API base
TRIGGERED_BY = "auditor_script"             # identifies THIS runner, not "manual"
STANDARDS_SHEET_REL = "docs/rules/global/coding-standards.md"
VALID_VERDICTS = ("pass", "reject")
CLAUDE_TIMEOUT_SECONDS = 300


def fail(msg, code=1):
    print(f"standards_audit: {msg}", file=sys.stderr)
    sys.exit(code)


# --- .env config (no hard-coded hosts/keys/models) ----------------------------
def load_env(repo_root):
    """Parse the repo .env into a dict. Config comes from here only."""
    env = {}
    path = os.path.join(repo_root, ".env")
    if not os.path.isfile(path):
        return env
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def resolve_config(env):
    api_base = env.get("STANDARDS_AUDIT_API_BASE") or env.get("VITE_API_BASE_URL")
    if not api_base:
        fail("no API base in .env (set STANDARDS_AUDIT_API_BASE or VITE_API_BASE_URL)")
    model = env.get("STANDARDS_AUDIT_MODEL")
    if not model:
        fail("no STANDARDS_AUDIT_MODEL in .env (the auditor model is not hard-coded)")
    agent_id = env.get("STANDARDS_AUDIT_AGENT_ID")  # optional write attribution
    return api_base.rstrip("/"), model, agent_id


# --- Diff gathering -----------------------------------------------------------
def git(repo_root, *args):
    proc = subprocess.run(
        ["git", "-C", repo_root, *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        fail(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def gather_diff(repo_root, args):
    """Return (diff_text, pr_ref, diff_range) for the selected mode."""
    if args.branch:
        merge_base = git(repo_root, "merge-base", "master", args.branch).strip()
        if not merge_base:
            fail(f"could not find merge-base of master and '{args.branch}'")
        diff_range = f"{merge_base}..{args.branch}"
        diff = git(repo_root, "diff", diff_range)
        return diff, args.branch, diff_range
    if args.range:
        diff = git(repo_root, "diff", args.range)
        return diff, args.range, args.range
    # --staged
    diff = git(repo_root, "diff", "--staged")
    head = git(repo_root, "rev-parse", "--short", "HEAD").strip()
    return diff, f"staged@{head}", "staged"


# --- The fresh auditor --------------------------------------------------------
def build_prompt(sheet_text, diff_text):
    """Auditor prompt: ONLY the sheet + diff + strict output instructions."""
    return f"""You are a standards auditor. You have NO context beyond what is in this \
message: a coding-standards sheet and a code diff. Judge the diff ONLY against \
the sheet. Do not assume any team, author, project history, or prior discussion.

=== CODING STANDARDS SHEET (the single source of law) ===
{sheet_text}

=== CODE DIFF UNDER AUDIT ===
{diff_text if diff_text.strip() else "(empty diff)"}

=== YOUR TASK ===
Return a verdict of "pass" (no violations) or "reject" (one or more violations).
List every violation you find, each tied to a specific section of the sheet.
Suggest a per-agent scorecard: a signed integer delta (carrot for good practice,
stick for a violation) with a one-line reason. If author identity is unknown,
use "author" as the agent name.

=== OUTPUT FORMAT — CRITICAL ===
Respond with STRICT JSON and NOTHING ELSE. No markdown, no code fences, no prose
before or after. The JSON MUST have exactly these keys:
{{
  "verdict": "pass" | "reject",
  "violations": [
    {{"rule": "<sheet section name>", "file": "<path>", "line": <int or null>,
      "note": "<what is wrong>", "severity": "low" | "medium" | "high"}}
  ],
  "scorecard": [
    {{"agent": "<name>", "delta": <signed integer>, "reason": "<one line>"}}
  ],
  "summary": "<short human-readable block: PASS or REJECT, then the violations>"
}}
If there are no violations, "violations" is [] and "verdict" is "pass"."""


def run_auditor(prompt, model):
    """Spawn `claude -p` from a throwaway cwd so no repo/team context loads.

    Returns the raw stdout string. Raises via fail() on invocation error.
    """
    with tempfile.TemporaryDirectory(prefix="std-audit-") as sandbox:
        try:
            proc = subprocess.run(
                ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
                capture_output=True, text=True, cwd=sandbox,
                timeout=CLAUDE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            fail("`claude` CLI not found on PATH — cannot spawn the auditor")
        except subprocess.TimeoutExpired:
            fail(f"auditor timed out after {CLAUDE_TIMEOUT_SECONDS}s")
        if proc.returncode != 0:
            fail(f"auditor exited {proc.returncode}: {proc.stderr.strip()[:400]}")
        return proc.stdout


def parse_auditor_json(raw):
    """Strip any fencing and json.loads. Returns dict or None (never raises)."""
    text = raw.strip()
    # Tolerate a ```json ... ``` fence even though the prompt forbids it.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        # Otherwise, clip to the outermost brace pair.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def validate_audit(obj):
    """Enforce required keys/types. Returns a normalized dict or fails loudly."""
    if not isinstance(obj, dict):
        fail("auditor output is not a JSON object")
    for key in ("verdict", "violations", "scorecard", "summary"):
        if key not in obj:
            fail(f"auditor output missing required key: '{key}'")
    if obj["verdict"] not in VALID_VERDICTS:
        fail(f"auditor verdict '{obj['verdict']}' not in {VALID_VERDICTS}")
    if not isinstance(obj["violations"], list):
        fail("auditor 'violations' is not a list")
    if not isinstance(obj["scorecard"], list):
        fail("auditor 'scorecard' is not a list")
    norm_violations = []
    for v in obj["violations"]:
        if not isinstance(v, dict):
            fail("a violation entry is not an object")
        norm_violations.append({
            "rule": str(v.get("rule", "")),
            "file": v.get("file"),
            "line": v.get("line"),
            "note": str(v.get("note", "")),
            "severity": v.get("severity") or "medium",
        })
    norm_scorecard = []
    for s in obj["scorecard"]:
        if not isinstance(s, dict):
            fail("a scorecard entry is not an object")
        try:
            delta = int(s.get("delta", 0))
        except (TypeError, ValueError):
            fail(f"scorecard delta not an integer: {s.get('delta')!r}")
        norm_scorecard.append({
            "agent": str(s.get("agent", "author")),
            "delta": delta,
            "reason": str(s.get("reason", "")),
        })
    return {
        "verdict": obj["verdict"],
        "violations": norm_violations,
        "scorecard": norm_scorecard,
        "summary": str(obj["summary"]),
    }


# --- Uniform human scorecard (printed on EVERY run) ---------------------------
def render_uniform_block(audit, pr_ref, diff_range):
    lines = []
    thumb = "PASS" if audit["verdict"] == "pass" else "REJECT"
    lines.append("=" * 60)
    lines.append(f"STANDARDS AUDIT: {thumb}")
    lines.append(f"  ref: {pr_ref}   range: {diff_range}")
    lines.append("=" * 60)
    if audit["violations"]:
        lines.append(f"Violations ({len(audit['violations'])}):")
        for v in audit["violations"]:
            loc = v["file"] or "?"
            if v["line"] is not None:
                loc = f"{loc}:{v['line']}"
            lines.append(f"  - [{v['severity']}] {v['rule']} @ {loc}")
            lines.append(f"      {v['note']}")
    else:
        lines.append("Violations: none")
    lines.append("")
    if audit["scorecard"]:
        lines.append("Scorecard (suggested; NOT applied by this runner):")
        for s in audit["scorecard"]:
            sign = f"+{s['delta']}" if s["delta"] >= 0 else str(s["delta"])
            lines.append(f"  {s['agent']}: {sign}  ({s['reason']})")
    else:
        lines.append("Scorecard: (none suggested)")
    lines.append("=" * 60)
    return "\n".join(lines)


# --- Payload + POST (the ONE place the endpoint shape lives) ------------------
def build_payload(audit, args, pr_ref, diff_range, diff_text, uniform_block):
    """Map validated auditor output -> the DWB standards-audit create payload.

    This function is the single source of the wire shape. If DWB-014's contract
    shifts, change it here only.
    """
    return {
        "project_id": args.project_id,
        "pr_ref": pr_ref,
        "diff_range": diff_range,
        "ticket_id": args.ticket_id,
        "sprint_id": args.sprint_id,
        "verdict": audit["verdict"],
        "violations": audit["violations"],
        "scorecard": audit["scorecard"],
        "summary": uniform_block,
        "details": diff_text,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "triggered_by": TRIGGERED_BY,
    }


def post_audit(api_base, payload, agent_id=None):
    """POST to the standards-audit endpoint. Endpoint path lives here only."""
    url = f"{api_base}{AUDIT_ENDPOINT_PATH}"
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    # Optional write attribution — set STANDARDS_AUDIT_AGENT_ID in .env to log
    # the POST against a specific agent; omitted -> logged as "system".
    if agent_id:
        headers["X-Agent-ID"] = str(agent_id)
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 404:
            # TODO(DWB-015): expected only if DWB-014 is not deployed. The
            # endpoint is LIVE as of Barry's merge; a 404 here means a wrong
            # API base in .env or the API is down.
            fail(f"POST {url} -> 404. Endpoint missing (check .env API base / API up). {detail}")
        fail(f"POST {url} -> {e.code}: {detail[:600]}")
    except urllib.error.URLError as e:
        fail(f"POST {url} failed: {e.reason}")


# --- CLI ----------------------------------------------------------------------
def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="run_standards_audit.sh",
        description="Spawn a fresh headless standards auditor over a diff and record the scorecard.",
    )
    p.add_argument("--repo-root", required=True, help="repo root (injected by the wrapper)")
    p.add_argument("--project-id", type=int, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--branch", help="diff this branch vs merge-base with master")
    mode.add_argument("--range", help="diff an explicit git range a..b")
    mode.add_argument("--staged", action="store_true", help="diff the staged changes")
    p.add_argument("--ticket-id", type=int, default=None)
    p.add_argument("--sprint-id", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="print payload + scorecard; do NOT POST")
    return p.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    repo_root = args.repo_root

    env = load_env(repo_root)
    api_base, model, agent_id = resolve_config(env)

    sheet_path = os.path.join(repo_root, STANDARDS_SHEET_REL)
    if not os.path.isfile(sheet_path):
        fail(f"standards sheet not found at {STANDARDS_SHEET_REL}")
    with open(sheet_path, "r") as fh:
        sheet_text = fh.read()

    diff_text, pr_ref, diff_range = gather_diff(repo_root, args)
    if not diff_text.strip():
        fail("empty diff — nothing to audit for the selected ref/range/staged set", code=2)

    prompt = build_prompt(sheet_text, diff_text)

    raw = run_auditor(prompt, model)
    audit = parse_auditor_json(raw)
    if audit is None:
        # Retry once with a terse "return only JSON" reminder appended.
        print("standards_audit: auditor output was not valid JSON; retrying once...", file=sys.stderr)
        raw = run_auditor(prompt + "\n\nREMINDER: Return ONLY the JSON object. No prose, no fences.", model)
        audit = parse_auditor_json(raw)
        if audit is None:
            fail("auditor returned non-JSON twice; not posting. Raw output:\n" + raw[:1000])
    audit = validate_audit(audit)

    uniform_block = render_uniform_block(audit, pr_ref, diff_range)
    # The uniform human block prints on EVERY run — this is what humans read.
    print(uniform_block)

    payload = build_payload(audit, args, pr_ref, diff_range, diff_text, uniform_block)

    if args.dry_run:
        print("\n--- DRY RUN: payload NOT posted ---")
        preview = dict(payload)
        preview["details"] = f"<{len(diff_text)} bytes of raw diff omitted>"
        print(json.dumps(preview, indent=2))
        return 0

    status, resp = post_audit(api_base, payload, agent_id)
    try:
        audit_id = json.loads(resp).get("id")
    except (json.JSONDecodeError, ValueError, AttributeError):
        audit_id = None
    print(f"\nRecorded standards audit (HTTP {status}, id={audit_id}) at {api_base}{AUDIT_ENDPOINT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
