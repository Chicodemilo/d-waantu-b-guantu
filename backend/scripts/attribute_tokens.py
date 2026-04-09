#!/usr/bin/env python3
# Path: backend/scripts/attribute_tokens.py
# File: attribute_tokens.py
# Created: 2026-03-28
# Purpose: Scan Claude transcript JSONL files and attribute token usage to tickets
# Caller: run_token_scan.sh, manual CLI, sprint completion trigger
# Callees: urllib → GET /api/agents, GET /api/tickets, POST /api/tracking/tokens, POST /api/alerts
# Data In: CLI args (--project-id, --dry-run, --force, --transcript-dir); JSONL transcripts
# Data Out: JSON summary to stdout; HTTP POSTs to API; state file updates
# Last Modified: 2026-03-30
"""Scan Claude transcript JSONL files and attribute tokens to tickets.

Reads transcript files from Claude Code's project directories, identifies
which agent produced each transcript, counts token usage, and POSTs the
totals to the LAT API.

Usage:
    python scripts/attribute_tokens.py                         # scan + attribute
    python scripts/attribute_tokens.py --dry-run               # scan only, no POST
    python scripts/attribute_tokens.py --project-id 1          # override project
    python scripts/attribute_tokens.py --transcript-dir <path> # override scan dir

Environment variables (all optional):
    LAT_API_URL              — API base URL (default: http://localhost:8000)
    LAT_DEFAULT_PROJECT_ID   — fallback project ID (default: 1)
    LAT_TOKEN_SANITY_CAP     — max tokens per transcript (default: 50000000)
    LAT_TRANSCRIPT_DIR       — transcript directory to scan (default: auto-detected)
    LAT_TOKEN_STATE_FILE     — state file tracking already-attributed sessions
                               (default: /tmp/lat_token_attribution_state.json)

Always exits 0. Posts alerts on failures.
"""

import argparse
import json
import os
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = os.environ.get("LAT_API_URL", "http://localhost:8000")
DEFAULT_PROJECT_ID = int(os.environ.get("LAT_DEFAULT_PROJECT_ID", "1"))
TOKEN_SANITY_CAP = int(os.environ.get("LAT_TOKEN_SANITY_CAP", "50000000"))
STATE_FILE = os.environ.get(
    "LAT_TOKEN_STATE_FILE", "/tmp/lat_token_attribution_state.json"
)
FALLBACK_AGENT_ID = int(os.environ.get("LAT_FALLBACK_AGENT_ID", "1"))

# Claude stores transcripts under ~/.claude/projects/<encoded-path>/
# The project working dir /Users/mchick/Dev/d-waantu_b-guantu encodes to:
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def get_json(url):
    req = urllib.request.Request(
        url, headers={"Content-Type": "application/json"}, method="GET"
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode())


def post_json(url, data):
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode())


def post_alert(title, body, project_id=None, agent_id=None):
    if project_id is None:
        project_id = DEFAULT_PROJECT_ID
    if agent_id is None:
        agent_id = FALLBACK_AGENT_ID
    try:
        post_json(f"{API_BASE}/api/alerts", {
            "project_id": project_id,
            "raised_by_agent_id": agent_id,
            "ticket_id": None,
            "title": title,
            "body": body,
            "severity": "info",
        })
    except Exception:
        pass


def find_transcript_dirs():
    """Find Claude project directories that match this project."""
    dirs = []
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return dirs
    for d in CLAUDE_PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        # Match dirs whose name encodes a path containing d-waantu_b-guantu
        # or d-waantu-b-guantu (also legacy local-agent-tracker)
        name = d.name.lower()
        if "d-waantu-b-guantu" in name or "d-waantu_b-guantu" in name or "local-agent-tracker" in name or "local_agent_tracker" in name:
            dirs.append(d)
    return sorted(dirs)


def read_transcript_metadata(path):
    """Read agentName, teamName, and timestamp range from a transcript."""
    agent_name = ""
    team_name = ""
    first_ts = None
    last_ts = None

    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_str = entry.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except (ValueError, TypeError):
                    pass

            if not agent_name and entry.get("type") == "assistant":
                agent_name = entry.get("agentName", "")
                team_name = entry.get("teamName", "")

    return {
        "agent_name": agent_name,
        "team_name": team_name,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def count_tokens(path):
    """Sum all token usage from assistant messages."""
    total = 0
    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            usage = entry.get("message", {}).get("usage", {})
            total += usage.get("input_tokens", 0)
            total += usage.get("cache_creation_input_tokens", 0)
            total += usage.get("cache_read_input_tokens", 0)
            total += usage.get("output_tokens", 0)
    return total


def load_state():
    """Load the set of already-attributed session IDs and their token counts."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def resolve_agent_id(agent_name, agents_cache):
    """Match an agentName (e.g. 'system-ops') to a LAT agent by role or name."""
    if not agent_name:
        return None
    al = agent_name.lower()
    for agent in agents_cache:
        if agent.get("role", "").lower() == al:
            return agent["id"]
    for agent in agents_cache:
        if agent["name"].lower() == al:
            return agent["id"]
    return None


def find_best_ticket(agent_id, project_id, first_ts, last_ts):
    """Find the best ticket to attribute tokens to.

    Strategy:
      1. Agent's in_progress tickets in this project → best match
      2. Agent's todo tickets in this project → fallback
      3. If multiple, prefer the one that overlaps the transcript time window
      4. If still ambiguous, return all for proportional split
    """
    candidates = []

    for status in ("in_progress", "todo"):
        params = f"project_id={project_id}&status={status}"
        if agent_id:
            params += f"&assigned_agent_id={agent_id}"
        try:
            tickets = get_json(f"{API_BASE}/api/tickets?{params}")
        except Exception:
            continue

        if tickets:
            candidates.extend(tickets)
            if status == "in_progress" and tickets:
                break  # in_progress is preferred, don't also fetch todo

    if not candidates:
        return []

    # Deduplicate by ID
    seen = set()
    unique = []
    for t in candidates:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)

    return unique


def attribute_tokens_to_tickets(tickets, tokens, agent_id=None, dry_run=False):
    """POST tokens to ticket(s) via /api/tracking/tokens. Splits proportionally if multiple."""
    results = []

    def _post_tracking(ticket, token_count):
        """Post a token_report event through the tracking API."""
        payload = {
            "ticket_id": ticket["id"],
            "agent_id": agent_id or ticket.get("assigned_agent_id") or FALLBACK_AGENT_ID,
            "tokens": token_count,
            "source": "transcript_scan",
        }
        return post_json(f"{API_BASE}/api/tracking/tokens", payload)

    if len(tickets) == 1:
        ticket = tickets[0]
        if not dry_run:
            try:
                _post_tracking(ticket, tokens)
                results.append({"ticket_id": ticket["id"], "ticket_key": ticket.get("ticket_key", ""), "tokens": tokens, "status": "posted"})
            except Exception as exc:
                results.append({"ticket_id": ticket["id"], "ticket_key": ticket.get("ticket_key", ""), "tokens": tokens, "status": f"failed: {exc}"})
        else:
            results.append({"ticket_id": ticket["id"], "ticket_key": ticket.get("ticket_key", ""), "tokens": tokens, "status": "dry-run"})
    elif len(tickets) > 1:
        # Split proportionally (equal split since we lack better signal)
        per_ticket = tokens // len(tickets)
        remainder = tokens - (per_ticket * len(tickets))
        for i, ticket in enumerate(tickets):
            share = per_ticket + (remainder if i == 0 else 0)
            if share <= 0:
                continue
            if not dry_run:
                try:
                    _post_tracking(ticket, share)
                    results.append({"ticket_id": ticket["id"], "ticket_key": ticket.get("ticket_key", ""), "tokens": share, "status": "posted"})
                except Exception as exc:
                    results.append({"ticket_id": ticket["id"], "ticket_key": ticket.get("ticket_key", ""), "tokens": share, "status": f"failed: {exc}"})
            else:
                results.append({"ticket_id": ticket["id"], "ticket_key": ticket.get("ticket_key", ""), "tokens": share, "status": "dry-run"})

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scan Claude transcripts and attribute tokens to tickets"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and report without POSTing")
    parser.add_argument("--project-id", type=int, default=None,
                        help=f"Project ID (default: {DEFAULT_PROJECT_ID})")
    parser.add_argument("--transcript-dir", type=str, default=None,
                        help="Override transcript directory")
    parser.add_argument("--force", action="store_true",
                        help="Re-process already-attributed sessions")
    args = parser.parse_args()

    project_id = args.project_id or DEFAULT_PROJECT_ID

    print(f"\n{'='*60}")
    print("  Token Attribution Scanner")
    print(f"{'='*60}\n")

    # Find transcript directories
    if args.transcript_dir:
        scan_dirs = [Path(args.transcript_dir)]
    else:
        env_dir = os.environ.get("LAT_TRANSCRIPT_DIR")
        if env_dir:
            scan_dirs = [Path(env_dir)]
        else:
            scan_dirs = find_transcript_dirs()

    if not scan_dirs:
        print("No transcript directories found.")
        return

    print(f"Scanning {len(scan_dirs)} directory(ies):")
    for d in scan_dirs:
        print(f"  {d}")
    print()

    # Fetch agents once
    try:
        agents_cache = get_json(f"{API_BASE}/api/agents")
    except Exception as exc:
        print(f"ERROR: Failed to fetch agents: {exc}")
        post_alert("Token scan failed", f"Could not fetch agents: {exc}", project_id=project_id)
        return

    # Load state
    state = load_state()

    # Collect all JSONL files
    jsonl_files = []
    for d in scan_dirs:
        jsonl_files.extend(d.glob("*.jsonl"))
        # Also check subagents directories
        for sub in d.glob("*/subagents/*/*.jsonl"):
            jsonl_files.append(sub)

    print(f"Found {len(jsonl_files)} transcript file(s)\n")

    # Process each transcript
    summary = {
        "processed": 0,
        "skipped_main": 0,
        "skipped_already": 0,
        "skipped_no_agent": 0,
        "skipped_no_ticket": 0,
        "skipped_zero": 0,
        "skipped_cap": 0,
        "attributed": 0,
        "total_tokens": 0,
        "details": [],
    }

    for jsonl_path in sorted(jsonl_files):
        session_id = jsonl_path.stem
        rel_path = jsonl_path.name

        # Skip already-attributed (unless --force)
        if not args.force and session_id in state:
            summary["skipped_already"] += 1
            continue

        # Read metadata
        try:
            meta = read_transcript_metadata(jsonl_path)
        except Exception:
            continue

        agent_name = meta["agent_name"]

        # Skip main sessions (no agentName = team lead)
        if not agent_name:
            summary["skipped_main"] += 1
            continue

        summary["processed"] += 1

        # Resolve agent
        agent_id = resolve_agent_id(agent_name, agents_cache)
        if not agent_id:
            log(f"{rel_path}: agent '{agent_name}' not found in DB — skipping")
            summary["skipped_no_agent"] += 1
            continue

        agent_info = next((a for a in agents_cache if a["id"] == agent_id), {})
        agent_label = f"{agent_info.get('name', '?')}/{agent_name}"

        # Check if overhead role (team-lead, pm) — skip for ticket attribution
        role = agent_info.get("role", "")
        if role in ("team-lead", "team_lead", "pm"):
            log(f"{rel_path}: {agent_label} is overhead role — skipping ticket attribution")
            summary["skipped_main"] += 1
            continue

        # Count tokens
        try:
            tokens = count_tokens(jsonl_path)
        except Exception:
            continue

        if tokens == 0:
            summary["skipped_zero"] += 1
            continue

        if tokens > TOKEN_SANITY_CAP:
            log(f"{rel_path}: {agent_label} has {tokens:,} tokens (exceeds cap) — skipping")
            summary["skipped_cap"] += 1
            post_alert(
                "Token count too high",
                f"Transcript {rel_path} for {agent_label} has {tokens:,} tokens (cap: {TOKEN_SANITY_CAP:,})",
                project_id=project_id,
                agent_id=agent_id,
            )
            continue

        # Find best ticket
        tickets = find_best_ticket(agent_id, project_id, meta["first_ts"], meta["last_ts"])
        if not tickets:
            log(f"{rel_path}: {agent_label} — {tokens:,} tokens but no matching ticket")
            summary["skipped_no_ticket"] += 1
            continue

        # Attribute
        results = attribute_tokens_to_tickets(tickets, tokens, agent_id=agent_id, dry_run=args.dry_run)
        for r in results:
            status_icon = "+" if "posted" in r["status"] else "~" if "dry" in r["status"] else "!"
            log(f"{rel_path}: {agent_label} → {r['ticket_key']} = {r['tokens']:,} tokens [{r['status']}]")
            summary["details"].append({
                "session": session_id,
                "agent": agent_label,
                "ticket_key": r["ticket_key"],
                "tokens": r["tokens"],
                "status": r["status"],
            })

        summary["attributed"] += 1
        summary["total_tokens"] += tokens

        # Mark as attributed
        if not args.dry_run:
            state[session_id] = {
                "tokens": tokens,
                "agent": agent_label,
                "attributed_at": datetime.now(timezone.utc).isoformat(),
            }

    # Save state
    if not args.dry_run:
        save_state(state)

    # Print summary
    print(f"\n{'='*60}")
    print("  Results")
    print(f"{'='*60}\n")
    print(f"  Transcripts found:     {len(jsonl_files)}")
    print(f"  Processed (teammate):  {summary['processed']}")
    print(f"  Skipped (main/overhead):{summary['skipped_main']}")
    print(f"  Skipped (already done):{summary['skipped_already']}")
    print(f"  Skipped (no agent):    {summary['skipped_no_agent']}")
    print(f"  Skipped (no ticket):   {summary['skipped_no_ticket']}")
    print(f"  Skipped (0 tokens):    {summary['skipped_zero']}")
    print(f"  Skipped (over cap):    {summary['skipped_cap']}")
    print(f"  Attributed:            {summary['attributed']}")
    print(f"  Total tokens:          {summary['total_tokens']:,}")
    if args.dry_run:
        print(f"\n  (dry-run — nothing was POSTed)")
    print()

    # Return summary for wrapper script
    json.dump(summary, sys.stdout)
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            post_alert(
                "Token attribution scan failed",
                f"Unhandled error: {traceback.format_exc()[-500:]}",
            )
        except Exception:
            pass
        traceback.print_exc()
    sys.exit(0)
