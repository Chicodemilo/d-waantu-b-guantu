#!/usr/bin/env python3
"""Claude Code Stop hook — reports token usage to LAT API.

Reads session data from stdin (Stop hook JSON), parses the transcript
JSONL for token usage, and POSTs the total to the ticket endpoint.

Designed to work with ZERO env vars. All env vars are optional overrides:

Runtime context (set per-agent if needed):
  ACTIVE_TICKET_ID       — ticket to attribute tokens to (auto-detected if unset)
  ACTIVE_PROJECT_ID      — project context (default: 1)
  ACTIVE_AGENT_ID        — agent ID (auto-detected from transcript agentName)
  ACTIVE_AGENT_ROLE      — agent role (auto-detected from agent lookup)

Script configuration:
  LAT_API_URL            — API base URL (default: http://localhost:8000)
  LAT_DEFAULT_PROJECT_ID — fallback project ID when ACTIVE_PROJECT_ID unset (default: 1)
  LAT_TOKEN_SANITY_CAP   — max tokens before flagging as suspicious (default: 10000000)
  LAT_DEBUG_LOG          — debug log file path (default: /tmp/lat_hook_debug.log)
  LAT_TOKEN_STATE_FILE   — delta tracking state file (default: /tmp/lat_token_state.json)
  LAT_FALLBACK_AGENT_ID  — agent ID for alerts when no agent resolved (default: 1)
  LAT_EVENT_DUMP_DIR     — directory for stop event JSON dumps (default: /tmp)

Agent detection strategy:
  1. ACTIVE_AGENT_ID env var if set
  2. Read agentName from the transcript (teammates have this on every
     assistant entry — it's the kebab-case role like "system-ops")
  3. Match agentName against LAT agent roles, then names

Session validation:
  - Teammate sessions have agentName/teamName fields → allowed
  - Subagent sessions live under /subagents/ → allowed
  - Bare top-level sessions (no team identity) → blocked (team lead session)
  - 10M token sanity cap catches anything else

On failure, posts an info alert to /api/alerts. Always exits 0.
"""

import json
import os
import sys
import time
import traceback
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

API_BASE = os.environ.get("LAT_API_URL", "http://localhost:8000")
DEFAULT_PROJECT_ID = int(os.environ.get("LAT_DEFAULT_PROJECT_ID", "1"))
TOKEN_SANITY_CAP = int(os.environ.get("LAT_TOKEN_SANITY_CAP", "10000000"))
DEBUG_LOG = os.environ.get("LAT_DEBUG_LOG", "/tmp/lat_hook_debug.log")
TOKEN_STATE_FILE = os.environ.get("LAT_TOKEN_STATE_FILE", "/tmp/lat_token_state.json")
FALLBACK_AGENT_ID = int(os.environ.get("LAT_FALLBACK_AGENT_ID", "1"))
EVENT_DUMP_DIR = os.environ.get("LAT_EVENT_DUMP_DIR", "/tmp")


def debug_log(msg):
    """Append a timestamped debug line to the debug log file."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def post_json(url, data):
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    return urllib.request.urlopen(req, timeout=5)


def get_json(url):
    req = urllib.request.Request(
        url, headers={"Content-Type": "application/json"}, method="GET"
    )
    resp = urllib.request.urlopen(req, timeout=5)
    return json.loads(resp.read().decode())


def post_alert(title, body, project_id=None, agent_id=None):
    """Post an info alert. Works even with zero env vars via hardcoded defaults."""
    if project_id is None:
        pid = os.environ.get("ACTIVE_PROJECT_ID", "").strip()
        project_id = int(pid) if pid.isdigit() else DEFAULT_PROJECT_ID
    if agent_id is None:
        aid = os.environ.get("ACTIVE_AGENT_ID", "").strip()
        agent_id = int(aid) if aid.isdigit() else None
    if agent_id is None:
        agent_id = FALLBACK_AGENT_ID  # Fallback so alert is visible
    alert = {
        "project_id": project_id,
        "raised_by_agent_id": agent_id,
        "ticket_id": None,
        "title": title,
        "body": body,
        "severity": "info",
    }
    try:
        post_json(f"{API_BASE}/api/alerts", alert)
    except Exception:
        pass


def read_transcript_metadata(transcript_path):
    """Read agentName and teamName from the first assistant entry in the transcript.

    Teammate sessions have these fields on every assistant entry:
      agentName: "system-ops" (kebab-case role/name)
      teamName: "lat-sprint" (team name)
    Main sessions and Agent-tool subagents do NOT have these fields.
    """
    try:
        with open(transcript_path) as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("type") == "assistant":
                    return {
                        "agent_name": entry.get("agentName", ""),
                        "team_name": entry.get("teamName", ""),
                    }
    except Exception:
        pass
    return {"agent_name": "", "team_name": ""}


def resolve_agent_id(hook_input, transcript_meta):
    """Resolve agent ID. Priority: env var > teammate_name > transcript agentName > hook agent_type."""
    env_id = os.environ.get("ACTIVE_AGENT_ID", "").strip()
    if env_id.isdigit():
        return int(env_id)

    # Collect candidate names to match against LAT agents
    candidates = []

    # TeammateIdle provides teammate_name directly
    teammate_name = hook_input.get("teammate_name", "")
    if teammate_name:
        candidates.append(teammate_name)

    # Transcript agentName (e.g., "system-ops", "frontend-worker")
    agent_name = transcript_meta.get("agent_name", "")
    if agent_name and agent_name not in candidates:
        candidates.append(agent_name)

    # Hook agent_type (e.g., "general-purpose" — rarely matches, but try)
    agent_type = hook_input.get("agent_type", "")
    if agent_type and agent_type not in candidates:
        candidates.append(agent_type)

    if not candidates:
        return None

    try:
        agents = get_json(f"{API_BASE}/api/agents")
        for candidate in candidates:
            cl = candidate.lower()
            for agent in agents:
                # Match by role (most common for teammates: agentName == role)
                if agent.get("role", "").lower() == cl:
                    return agent["id"]
                # Match by name
                if agent["name"].lower() == cl:
                    return agent["id"]
    except Exception:
        pass
    return None


def resolve_agent_role(agent_id):
    """Look up agent role from the API."""
    env_role = os.environ.get("ACTIVE_AGENT_ROLE", "").strip()
    if env_role:
        return env_role
    if agent_id is None:
        return ""
    try:
        agent = get_json(f"{API_BASE}/api/agents/{agent_id}")
        return agent.get("role", "")
    except Exception:
        return ""


def resolve_project_id():
    """Resolve project ID from env var or default."""
    env_pid = os.environ.get("ACTIVE_PROJECT_ID", "").strip()
    return int(env_pid) if env_pid.isdigit() else DEFAULT_PROJECT_ID


def detect_ticket_id(agent_id=None):
    """Auto-detect an active ticket (in_progress or todo).

    Strategy:
      1. If agent_id is known, look for in_progress then todo tickets assigned to them.
      2. Otherwise, look for ALL in_progress then todo tickets.
      3. Prefer in_progress over todo. Return ticket ID if exactly one match.
    """
    try:
        if agent_id is not None:
            for status in ("in_progress", "todo"):
                url = f"{API_BASE}/api/tickets?status={status}&assigned_agent_id={agent_id}"
                tickets = get_json(url)
                if len(tickets) == 1:
                    return str(tickets[0]["id"])

        for status in ("in_progress", "todo"):
            url = f"{API_BASE}/api/tickets?status={status}"
            tickets = get_json(url)
            if len(tickets) == 1:
                return str(tickets[0]["id"])
    except Exception:
        pass
    return None


def count_tokens(transcript_path):
    """Sum token usage from assistant messages in the transcript JSONL."""
    total_input = 0
    total_output = 0
    with open(transcript_path) as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("type") != "assistant":
                continue
            usage = entry.get("message", {}).get("usage", {})
            total_input += usage.get("input_tokens", 0)
            total_input += usage.get("cache_creation_input_tokens", 0)
            total_input += usage.get("cache_read_input_tokens", 0)
            total_output += usage.get("output_tokens", 0)
    return total_input + total_output


def get_reported_tokens(session_id):
    """Read how many tokens we already reported for this session."""
    try:
        with open(TOKEN_STATE_FILE) as f:
            state = json.load(f)
        return state.get(session_id, 0)
    except Exception:
        return 0


def set_reported_tokens(session_id, total):
    """Store the cumulative token count we've reported for this session."""
    try:
        try:
            with open(TOKEN_STATE_FILE) as f:
                state = json.load(f)
        except Exception:
            state = {}
        state[session_id] = total
        with open(TOKEN_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def main():
    debug_log("=== Hook fired ===")

    # Read and dump the Stop event JSON
    try:
        raw_stdin = sys.stdin.read()
        debug_log(f"Raw stdin length: {len(raw_stdin)}")
        hook_input = json.loads(raw_stdin)
    except Exception as exc:
        debug_log(f"Failed to parse stdin: {exc}")
        return

    # Dump the full Stop event to a file for inspection
    try:
        dump_path = f"{EVENT_DUMP_DIR}/lat_stop_event_{int(time.time())}.json"
        with open(dump_path, "w") as f:
            json.dump(hook_input, f, indent=2)
        debug_log(f"Stop event dumped to {dump_path}")
    except Exception:
        pass

    event_name = hook_input.get("hook_event_name", "Stop")
    debug_log(f"Hook input keys: {list(hook_input.keys())}")
    debug_log(f"  hook_event_name: {event_name}")
    debug_log(f"  session_id: {hook_input.get('session_id', 'MISSING')}")
    debug_log(f"  agent_type: {hook_input.get('agent_type', 'MISSING')}")
    debug_log(f"  agent_id: {hook_input.get('agent_id', 'MISSING')}")
    debug_log(f"  teammate_name: {hook_input.get('teammate_name', 'MISSING')}")
    debug_log(f"  team_name: {hook_input.get('team_name', 'MISSING')}")
    debug_log(f"  transcript_path: {hook_input.get('transcript_path', 'MISSING')}")
    debug_log(f"  agent_transcript_path: {hook_input.get('agent_transcript_path', 'MISSING')}")
    debug_log(f"  stop_hook_active: {hook_input.get('stop_hook_active', 'MISSING')}")

    # Determine transcript path based on event type
    # SubagentStop provides agent_transcript_path (the subagent's own transcript)
    # TeammateIdle and Stop provide transcript_path (may be parent session)
    if event_name == "SubagentStop":
        transcript_path = hook_input.get("agent_transcript_path", "") or hook_input.get("transcript_path", "")
    else:
        transcript_path = hook_input.get("transcript_path", "")

    if not transcript_path:
        debug_log("BAIL: no transcript_path")
        return
    transcript_path = os.path.expanduser(transcript_path)
    if not os.path.isfile(transcript_path):
        debug_log(f"BAIL: transcript not found at {transcript_path}")
        return

    debug_log(f"Transcript exists: {os.path.getsize(transcript_path)} bytes")

    # Determine agent identity based on event type
    # TeammateIdle gives us teammate_name directly (e.g., "system-ops")
    # SubagentStop gives us agent_type (e.g., "Explore", "general-purpose")
    # Stop gives us the main session (team lead) — usually skip
    teammate_name = hook_input.get("teammate_name", "")
    transcript_meta = {"agent_name": "", "team_name": ""}

    if event_name == "TeammateIdle" and teammate_name:
        # TeammateIdle gives identity directly — no need to parse transcript
        transcript_meta = {
            "agent_name": teammate_name,
            "team_name": hook_input.get("team_name", ""),
        }
        debug_log(f"TeammateIdle: teammate_name={teammate_name!r} team_name={hook_input.get('team_name', '')!r}")
    elif event_name == "SubagentStop":
        # SubagentStop — read identity from the subagent's transcript
        transcript_meta = read_transcript_metadata(transcript_path)
        debug_log(f"SubagentStop: transcript agentName={transcript_meta['agent_name']!r}")
    else:
        # Stop event — read identity from transcript
        transcript_meta = read_transcript_metadata(transcript_path)

    is_teammate = bool(transcript_meta["agent_name"]) or bool(teammate_name)
    is_subagent = "/subagents/" in transcript_path or event_name == "SubagentStop"

    debug_log(f"Transcript meta: agentName={transcript_meta['agent_name']!r} teamName={transcript_meta['team_name']!r}")
    debug_log(f"is_teammate={is_teammate} is_subagent={is_subagent}")

    # Guard: block bare top-level sessions (team lead's main session)
    if not is_teammate and not is_subagent:
        debug_log("BAIL: bare top-level session (no agentName, not under /subagents/)")
        return

    # Resolve context
    agent_id = resolve_agent_id(hook_input, transcript_meta)
    agent_role = resolve_agent_role(agent_id)
    project_id = resolve_project_id()
    is_overhead = agent_role in ("team_lead", "team-lead", "pm")

    debug_log(f"Resolved: agent_id={agent_id} role={agent_role!r} project_id={project_id} is_overhead={is_overhead}")

    # Resolve ticket (non-overhead only)
    ticket_id = None
    if not is_overhead:
        env_tid = os.environ.get("ACTIVE_TICKET_ID", "").strip()
        if env_tid.isdigit():
            ticket_id = env_tid
            debug_log(f"Ticket from env: {ticket_id}")
        else:
            ticket_id = detect_ticket_id(agent_id)
            debug_log(f"Ticket auto-detected: {ticket_id}")

        if not ticket_id or not ticket_id.isdigit():
            agent_label = f"agent {agent_id} ({transcript_meta['agent_name']})" if agent_id else f"unknown agent (agentName={transcript_meta['agent_name']!r})"
            debug_log(f"BAIL: no ticket found for {agent_label}")
            post_alert(
                "Token tracking skipped",
                f"No active ticket found for {agent_label}. "
                "Set ACTIVE_TICKET_ID or ensure a ticket is in_progress/todo.",
                project_id=project_id,
                agent_id=agent_id,
            )
            return

    # Count tokens
    try:
        total_tokens = count_tokens(transcript_path)
    except Exception as exc:
        debug_log(f"BAIL: count_tokens failed: {exc}")
        return

    debug_log(f"Total tokens (cumulative): {total_tokens:,}")

    if total_tokens == 0:
        debug_log("BAIL: 0 tokens")
        return

    # Delta tracking: TeammateIdle fires repeatedly, so we only POST the
    # difference since last report. SubagentStop/Stop fire once — delta
    # tracking is still safe (first report = full amount).
    session_id = hook_input.get("session_id", "")
    previously_reported = get_reported_tokens(session_id) if session_id else 0
    delta_tokens = total_tokens - previously_reported

    debug_log(f"Previously reported: {previously_reported:,}, delta: {delta_tokens:,}")

    if delta_tokens <= 0:
        debug_log("BAIL: no new tokens since last report")
        return

    # Sanity cap (on cumulative total, not delta)
    if total_tokens > TOKEN_SANITY_CAP:
        debug_log(f"BAIL: tokens {total_tokens:,} exceed cap {TOKEN_SANITY_CAP:,}")
        post_alert(
            "Token count too high",
            f"Counted {total_tokens:,} tokens (cap is {TOKEN_SANITY_CAP:,}). "
            f"This likely indicates the wrong transcript was read. "
            f"Agent: {transcript_meta['agent_name'] or 'unknown'}, "
            f"Transcript: {transcript_path}",
            project_id=project_id,
            agent_id=agent_id,
        )
        return

    # POST delta tokens (increment endpoint adds to existing count)
    posted = False
    if is_overhead:
        url = f"{API_BASE}/api/projects/{project_id}/overhead"
        debug_log(f"POST overhead: {delta_tokens} delta tokens to {url}")
        try:
            post_json(url, {"role": agent_role, "tokens_used": delta_tokens})
            debug_log("POST overhead: SUCCESS")
            posted = True
        except Exception as exc:
            debug_log(f"POST overhead: FAILED {exc}")
            post_alert(
                "Overhead tracking failed",
                f"Failed to POST {delta_tokens} overhead tokens ({agent_role}) "
                f"to project {project_id}: {exc}",
                project_id=project_id,
                agent_id=agent_id,
            )
    else:
        url = f"{API_BASE}/api/tickets/{ticket_id}/tokens"
        debug_log(f"POST tokens: {delta_tokens} delta to {url}")
        try:
            post_json(url, {"tokens_used": delta_tokens, "time_spent_seconds": 0})
            debug_log("POST tokens: SUCCESS")
            posted = True
        except Exception as exc:
            debug_log(f"POST tokens: FAILED {exc}")
            post_alert(
                "Token tracking failed",
                f"Failed to POST {delta_tokens} tokens to ticket {ticket_id}: {exc}",
                project_id=project_id,
                agent_id=agent_id,
            )

    # Save state so next TeammateIdle only sends the delta
    if posted and session_id:
        set_reported_tokens(session_id, total_tokens)
        debug_log(f"State saved: session {session_id[:12]}... = {total_tokens:,} reported")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            post_alert(
                "Token tracking failed",
                f"Unhandled error in report_tokens hook: {traceback.format_exc()}",
            )
        except Exception:
            pass
    sys.exit(0)
