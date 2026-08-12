#!/usr/bin/env python3
# Path: scripts/standards_audit.py
# File: standards_audit.py
# Created: 2026-08-11
# Purpose: Standards-audit runner. Gathers a diff, spawns a FRESH headless
#   auditor (claude -p) whose ONLY context is the global coding-standards sheet
#   (plus the audited repo's Project Extensions section, if any) + the diff,
#   validates the auditor's strict JSON, prints a uniform human scorecard, and
#   POSTs the audit to the DWB standards-audit API (DWB-014).
# Caller: scripts/run_standards_audit.sh (thin wrapper); may also run directly.
# Callees: git (diff gathering), `claude -p` (the fresh auditor), the DWB API
#   POST /api/standards-audits.
# Data In: CLI flags (--project-id, one of --branch/--range/--staged, optional
#   --ticket-id/--author/--sprint-id/--dry-run). Config from .env only. When
#   --ticket-id or --author is given, resolves real roster names (author from the
#   ticket's assigned agent or --author; reviewer/PM from the project team) and
#   injects a facts-only ATTRIBUTION block so scorecards name real agents.
# Data Out: Exit 0 + a stored audit (or, with --dry-run, the payload printed).
#   Non-zero exit + a clear message on malformed auditor output, an unknown
#   scorecard name (DWB-023 pre-POST guard), or API failure.
# Last Modified: 2026-08-12 (DWB-029)
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
PROJECT_STANDARDS_REL = "CODING_STANDARDS.md"       # repo-root project sheet (DWB-029)
PROJECT_EXTENSIONS_MARKER = "## Project Extensions"  # section to EOF = added law
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


# --- Project extensions: per-repo law that ADDS to the global sheet (DWB-029) --
def load_project_extensions(repo_root):
    """Return the repo's '## Project Extensions' section (marker to EOF), or None.

    The audited repo may specialize/add law in its root CODING_STANDARDS.md below
    the marker (e.g. DWB sanctions hooks-for-view-logic). Without this the auditor
    only sees the global sheet and falsely rejects sanctioned patterns (audit 15).
    No file or no marker -> None, so the prompt is unchanged.
    """
    path = os.path.join(repo_root, PROJECT_STANDARDS_REL)
    if not os.path.isfile(path):
        return None
    with open(path, "r") as fh:
        text = fh.read()
    idx = text.find(PROJECT_EXTENSIONS_MARKER)
    if idx == -1:
        return None
    section = text[idx:].strip()
    return section or None


# --- Attribution: resolve real roster names for the scorecard (DWB-023) --------
def api_get_json(api_base, path):
    """GET {api_base}{path} and return parsed JSON, or fail loudly."""
    url = f"{api_base}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        fail(f"GET {url} -> {e.code}: {detail[:300]}")
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
        fail(f"GET {url} failed: {e}")


def resolve_team(api_base, project_id):
    """Return (by_id, tl_name, pm_name) from the project roster.

    by_id maps agent_id -> {"name", "role"}. tl_name/pm_name are the first
    team-lead / pm on the roster (or None). Names are facts, not opinions.
    """
    team = api_get_json(api_base, f"/projects/{project_id}/team")
    by_id, tl_name, pm_name = {}, None, None
    for a in team.get("agents", []):
        by_id[a["agent_id"]] = {"name": a["name"], "role": a["role"]}
        if a["role"] == "team-lead" and tl_name is None:
            tl_name = a["name"]
        elif a["role"] == "pm" and pm_name is None:
            pm_name = a["name"]
    return by_id, tl_name, pm_name


def resolve_attribution(api_base, args):
    """Derive author/reviewer/pm names for the scorecard, or None if not requested.

    Attribution is attempted only when --author or --ticket-id is supplied. The
    author comes from --author (explicit) or the ticket's assigned agent. TL/PM
    come from the project roster as optional review/scoping context.

    Returns {"author", "author_role", "reviewer", "pm"} (values may be None for
    reviewer/pm) or None when no attribution was requested. Fails loudly if
    attribution is requested but the author cannot be resolved.
    """
    if not args.author and args.ticket_id is None:
        return None  # backward-compatible: no names, generic "author"

    by_id, tl_name, pm_name = resolve_team(api_base, args.project_id)

    author_name, author_role = args.author, None
    if author_name:
        # Prefer the roster role if the explicit name is on the team.
        for info in by_id.values():
            if info["name"] == author_name:
                author_role = info["role"]
                break
    else:
        ticket = api_get_json(api_base, f"/tickets/{args.ticket_id}")
        assignee_id = ticket.get("assigned_agent_id")
        if not assignee_id or assignee_id not in by_id:
            fail(f"ticket {args.ticket_id} has no resolvable assigned agent; "
                 f"pass --author <agent_name> explicitly")
        author_name = by_id[assignee_id]["name"]
        author_role = by_id[assignee_id]["role"]

    return {
        "author": author_name,
        "author_role": author_role or "worker",
        "reviewer": tl_name,
        "pm": pm_name,
    }


def allowed_scorecard_names(attribution):
    """The exact set of names the auditor may use in scorecard entries."""
    if attribution is None:
        return {"author"}  # generic fallback, matches the no-attribution prompt
    names = {attribution["author"]}
    if attribution["reviewer"]:
        names.add(attribution["reviewer"])
    if attribution["pm"]:
        names.add(attribution["pm"])
    return names


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
def build_attribution_block(attribution):
    """Facts-only ATTRIBUTION block (names/roles). No opinions -> fresh eyes kept."""
    if attribution is None:
        return "", 'If author identity is unknown, use "author" as the agent name.'
    lines = ["=== ATTRIBUTION (facts only — names and roles; no opinions) ===",
             "The people associated with this change. Use these EXACT names in "
             "scorecard entries; do not invent names or use generic labels.",
             f"- Author (worker who made the change): {attribution['author']} "
             f"[role: {attribution['author_role']}]"]
    if attribution["reviewer"]:
        lines.append(f"- Reviewer (team lead): {attribution['reviewer']}")
    if attribution["pm"]:
        lines.append(f"- Project manager: {attribution['pm']}")
    block = "\n".join(lines) + "\n"
    rules = (
        "Scorecard attribution rules (use ONLY the names listed in ATTRIBUTION):\n"
        f"- Put worker deltas (for the change itself) on the Author "
        f"({attribution['author']}).\n"
        "- Add a Reviewer entry ONLY if a violation survived into already-reviewed "
        "work (repeat survival); otherwise omit the reviewer.\n"
        "- Add a PM entry ONLY on a clear ticketing/scoping signal in the diff; "
        "otherwise omit the PM.\n"
        "- Any name not listed in ATTRIBUTION is invalid."
    )
    return block, rules


def build_extensions_block(extensions_text):
    """Labeled additional-law block for this project's extensions (DWB-029)."""
    if not extensions_text:
        return ""
    return (
        "\n=== THIS PROJECT'S EXTENSIONS (additional law — they ADD to the global "
        "sheet above, never override it) ===\n"
        "Treat these as binding law alongside the global sheet. A pattern this "
        "section explicitly sanctions is NOT a violation, even if it looks unusual.\n"
        f"{extensions_text}\n"
    )


def build_prompt(sheet_text, diff_text, attribution=None, extensions_text=None):
    """Auditor prompt: the sheet (+ project extensions) + diff + attribution."""
    attribution_block, scorecard_rule = build_attribution_block(attribution)
    extensions_block = build_extensions_block(extensions_text)
    sources = "a coding-standards sheet"
    if extensions_text:
        sources += ", this project's standards extensions"
    if attribution:
        sources += ", a facts-only attribution block,"
    return f"""You are a standards auditor. You have NO context beyond what is in this \
message: {sources} and a code diff. \
Judge the diff ONLY against the sheet and this project's extensions (if present). \
Do not assume any project history or prior discussion. The attribution block, if \
present, lists names/roles ONLY — it is not an opinion about the work and must not \
sway your verdict.

=== CODING STANDARDS SHEET (the single source of law) ===
{sheet_text}
{extensions_block}{attribution_block}
=== CODE DIFF UNDER AUDIT ===
{diff_text if diff_text.strip() else "(empty diff)"}

=== YOUR TASK ===
Return a verdict of "pass" (no violations) or "reject" (one or more violations).
List every violation you find, each tied to a specific section of the sheet or
this project's extensions. Do not flag a pattern the extensions explicitly allow.
Suggest a per-agent scorecard: a signed integer delta (carrot for good practice,
stick for a violation) with a one-line reason.
{scorecard_rule}

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


def validate_audit(obj, allowed_names=None):
    """Enforce required keys/types. Returns a normalized dict or fails loudly.

    If allowed_names is given, every scorecard agent name must be in that set
    (unknown names fail loudly, pre-POST) — this is the DWB-023 guarantee that
    apply-scorecard can resolve every entry to the ledger.
    """
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
        agent_name = str(s.get("agent", "author"))
        if allowed_names is not None and agent_name not in allowed_names:
            fail(f"scorecard names an unknown agent '{agent_name}'; "
                 f"allowed: {sorted(allowed_names)}. Not posting (would mis-attribute the ledger).")
        norm_scorecard.append({
            "agent": agent_name,
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
    p.add_argument("--ticket-id", type=int, default=None,
                   help="associate the audit with a ticket; also derives the author agent")
    p.add_argument("--author", default=None,
                   help="explicit author agent name for scorecard attribution "
                        "(overrides the ticket's assigned agent)")
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

    # Resolve real roster names so scorecards attribute to the ledger (DWB-023).
    attribution = resolve_attribution(api_base, args)
    allowed_names = allowed_scorecard_names(attribution)
    if attribution:
        who = attribution["author"]
        extras = [n for n in (attribution["reviewer"], attribution["pm"]) if n]
        print(f"standards_audit: attribution -> author={who}"
              + (f", context={extras}" if extras else ""), file=sys.stderr)

    # Project extensions add per-repo law so sanctioned patterns aren't false-rejected (DWB-029).
    extensions_text = load_project_extensions(repo_root)
    if extensions_text:
        print(f"standards_audit: including project extensions from {PROJECT_STANDARDS_REL} "
              f"({len(extensions_text)} chars)", file=sys.stderr)

    diff_text, pr_ref, diff_range = gather_diff(repo_root, args)
    if not diff_text.strip():
        fail("empty diff — nothing to audit for the selected ref/range/staged set", code=2)

    prompt = build_prompt(sheet_text, diff_text, attribution, extensions_text)

    raw = run_auditor(prompt, model)
    audit = parse_auditor_json(raw)
    if audit is None:
        # Retry once with a terse "return only JSON" reminder appended.
        print("standards_audit: auditor output was not valid JSON; retrying once...", file=sys.stderr)
        raw = run_auditor(prompt + "\n\nREMINDER: Return ONLY the JSON object. No prose, no fences.", model)
        audit = parse_auditor_json(raw)
        if audit is None:
            fail("auditor returned non-JSON twice; not posting. Raw output:\n" + raw[:1000])
    audit = validate_audit(audit, allowed_names)

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
