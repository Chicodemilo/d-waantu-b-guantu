# Path: app/services/hook_tracking.py
# File: hook_tracking.py
# Created: 2026-04-09
# Purpose: Hook-based tracking service - handles Claude Code lifecycle hook events + DWB session phrase detection (DWB-336 Layer-1 regex, DWB-343 OPEN retry on session-end, DWB-344 UserPromptSubmit fast path, DWB-353 ad_hoc routing + alert removal, DWB-373 hook_session.dwb_session_id linker, DWB-390 agent-id-aware pending-marker claim, DWB-395 grace-window resurrect, DWB-402 Layer-2 Haiku classifier retired)
# Caller: app/routers/hooks.py
# Callees: app/models/hook_session.py, app/services/tracking.py, app/services/dwb_session.py, app/models/alert.py, app/config/session_phrases.py
# Data In: db: Session, hook event JSON from Claude Code hooks
# Data Out: HookSession records, tracking_log events via tracking.py, opened/closed/reopened DwbSession rows
# Last Modified: 2026-06-19 (DWB-402)
#
# DWB-377 (2026-06-11): UserPromptSubmit close fast-path. Mirrors DWB-344 on
# the close side - when match_open misses, try match_close and close the
# active DWB session if one exists.
# DWB-402 (2026-06-19): retired the Layer-2 Haiku AI classifier fallback
# (DWB-382). When both match_open AND match_close miss on UserPromptSubmit the
# handler returns a plain noop. Session lifecycle now rests on three paths: the
# deterministic /dwb-open + /dwb-close slash commands, the passive Layer-1
# regex, and the idle-timeout sweeper. The `ai_classifier` enum value is kept
# as a legacy tombstone so historical rows still load.

"""Service layer for passive hook-based time and token tracking.

Handles SessionStart, SessionEnd, and SubagentStop lifecycle hooks from
Claude Code. Creates hook_session records for state management and delegates
to tracking.py for authoritative event logging.
"""

import json
import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.session_phrases import match_close, match_open
from app.models.agent import Agent
# DWB-353: app.models.alert imports removed - the only consumer in this
# module was _create_unattributed_alert, which is gone.
from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.ticket import Ticket, TicketStatus
from app.services import dwb_session as dwb_svc
from app.services import tracking
from app.services.failed_hook import log_failed_hook

logger = logging.getLogger(__name__)

# Roles treated as overhead (not ticket work)
OVERHEAD_ROLES = {"team-lead", "pm"}


def _active_dwb_session_id(db: Session, project_id: int) -> int | None:
    """DWB-373: Resolve the active DWB session id for a project, or None.

    Wraps dwb_svc.get_active_session so HookSession inserts can stamp the
    enclosing window in one expression. Without this link the sessions list
    aggregator (_rollup_tokens) sums an empty set and reports 0 tokens for
    every closed DWB session - the symptom DWB-373 surfaced.

    DWB-395: this is also the grace-window resurrect hook-in point. Every
    hook_session insert / backfill flows through here, so it's exactly where
    "tracking activity landed" is observable. When no session is open we first
    attempt to resurrect a just-closed low-precision session (see
    ``_maybe_grace_resurrect_dwb_session``); the resurrected id is then returned
    so the incoming hook_session links to the reopened window rather than to a
    fresh session that would fragment the rollup.
    """
    active = dwb_svc.get_active_session(db, project_id)
    if active is not None:
        return active.id
    return _maybe_grace_resurrect_dwb_session(db, project_id)


# DWB-395: grace window for auto-resurrecting a just-closed DWB session.
#
# A low-precision close (a Layer-1 regex catalogue hit) can fire on text that
# wasn't really a close - e.g. TL prose like "shut down cycle" tripping the
# catalogue. When real tracking activity (a hook_session or tracking_log write)
# lands within this window of such a close, we treat the close as false and
# reopen the same session, rather than opening a brand-new one that splits the
# time/token rollup across two rows.
#
# Deliberate closes are NEVER auto-undone:
#   - slash        : the user explicitly typed /dwb-close
#   - ai_confident : the TL consciously closed with a headline
#   - ai_asked     : the TL closed after confirming with the user
#   - idle_timeout : the safety sweeper, which only fires when there was
#                    genuinely no activity for the idle window
# Only `regex` - the single low-precision, no-human-in-loop layer - is
# eligible. (DWB-402 retired the Layer-2 `ai_classifier`, which used to share
# this grace treatment.)
_GRACE_RESURRECT_SECONDS = 120
_GRACE_RESURRECT_METHODS = (DwbCloseMethod.regex,)


def _maybe_grace_resurrect_dwb_session(
    db: Session, project_id: int, now: datetime | None = None
) -> int | None:
    """DWB-395: reopen a just-closed low-precision DWB session when tracking
    activity lands inside the grace window. Returns the resurrected session id,
    or None when nothing was resurrected.

    Conditions (all must hold):
      - the project currently has NO open DWB session
      - its most-recently-closed session was closed via `regex` or
        `ai_classifier` (the low-precision layers)
      - that close happened within ``_GRACE_RESURRECT_SECONDS`` of ``now``

    Fire-and-forget contract, like the rest of this module: any failure is
    swallowed + logged to failed_hooks. Token/time attribution must never break
    because a resurrect attempt raised. The caller owns the commit (this runs
    inside the hook handler's transaction, alongside the hook_session insert).
    """
    try:
        # The caller only invokes this when no session is open, but re-check so
        # the helper is correct in isolation and after any racing open.
        if dwb_svc.get_active_session(db, project_id) is not None:
            return None

        recent = db.scalar(
            select(DwbSession)
            .where(DwbSession.project_id == project_id)
            .where(DwbSession.closed_at.isnot(None))
            .order_by(DwbSession.closed_at.desc())
            .limit(1)
        )
        if recent is None:
            return None
        if recent.close_method not in _GRACE_RESURRECT_METHODS:
            return None

        # closed_at is naive UTC; normalise the reference clock to match.
        ref = now or datetime.now(UTC)
        if ref.tzinfo is not None:
            ref = ref.astimezone(UTC).replace(tzinfo=None)
        elapsed = (ref - recent.closed_at).total_seconds()
        if elapsed > _GRACE_RESURRECT_SECONDS:
            return None

        resurrected, conflict = dwb_svc.reopen_session(db, recent)
        if resurrected is None or conflict is not None:
            # Lost a race to a concurrent open; leave it be.
            return None

        logger.info(
            "DWB-395 grace resurrect: reopened DWB session id=%s "
            "(closed via %s, %.0fs ago) for project_id=%s",
            recent.id,
            recent.close_method.value if recent.close_method else "?",
            elapsed,
            project_id,
        )
        return resurrected.id
    except Exception as e:
        logger.exception(
            "DWB-395 grace resurrect failed for project_id=%s", project_id
        )
        log_failed_hook(
            hook_event="dwb_session_grace_resurrect",
            status_code=None,
            raw_payload={"project_id": project_id},
            error=f"{type(e).__name__}: {e}",
        )
        return None

# Subdirectory under <project.repo_path>/.claude where per-session marker
# files live. Each marker is a JSON file named <session_id> containing
# {"agent_id": int} written by whatever component spawns the session.
_SESSION_MARKER_SUBPATH = ".claude/agents/active"

# DWB-304 pending-marker convention.
#
# CC's SubagentStop hook fires with an internally-generated session_id that
# the spawning TL cannot pre-compute. To attribute subagents correctly the TL
# writes a "pending" marker BEFORE calling Task(), keyed on agent identity
# rather than session_id:
#
#     pending-<agent_id>-<unix_ms>-<rand4hex>
#
# The resolver, when it can't find a marker named for the actual session_id,
# falls back to the oldest unconsumed pending marker for this project and
# atomically renames it to the session_id (the rename serves as the consume
# signal). Concurrent SubagentStops are race-safe because os.rename is atomic
# on POSIX — only one caller wins per pending marker.
_PENDING_MARKER_RE = re.compile(r"^pending-(\d+)-(\d+)-([0-9a-fA-F]{4})$")

# Pending markers older than this are garbage-collected on encounter. Most
# Task() spawns finish in seconds; 1h is generous and covers long workflows.
_PENDING_MARKER_STALE_SECONDS = 3600


def handle_session_start(db: Session, hook_data: dict) -> HookSession:
    """Handle a SessionStart hook event.

    1. Extract session_id, transcript_path, cwd
    2. Idempotent — return existing if session_id already exists
    3. Resolve project from cwd
    4. Quick-read transcript for agentName
    5. Resolve agent, determine session type
    6. Create HookSession(status=active)
    7. Log start via tracking.py
    """
    session_id = hook_data.get("session_id", "")
    if not session_id:
        raise ValueError("session_id is required")

    # Idempotent: return existing session
    existing = db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )
    if existing:
        return existing

    transcript_path = hook_data.get("transcript_path")
    cwd = hook_data.get("cwd", "")

    # Resolve project from cwd
    project = _resolve_project(db, cwd)
    if not project:
        raise ValueError(f"No project found for cwd: {cwd}")

    # 1. Authoritative path — read the session marker file. When the marker
    #    is missing or unparseable, log to failed_hooks and fall back to the
    #    transcript-name resolve below. The marker fixes the PM=50-tokens
    #    attribution drift (DWB-294).
    agent = resolve_agent_from_marker(
        db, project, session_id,
        hook_event=hook_data.get("hook_event_name") or "SessionStart",
        hook_data=hook_data,
    )
    agent_name: str | None = agent.name if agent else None

    # 2. Fallback path — extract agentName from hook data or transcript.
    if not agent:
        agent_name = hook_data.get("agent_name")
        if not agent_name and transcript_path:
            agent_name = _read_agent_name_from_transcript(transcript_path)
        agent = resolve_agent(db, agent_name, project.id) if agent_name else None

    # Main CLI session (no agent name) → attribute as TL overhead
    if not agent:
        agent = _fallback_tl_agent(db, project.id)
        if agent:
            agent_name = agent.role

    session_type = _determine_session_type(agent)

    # Resolve work context for workers
    ticket = None
    sprint_id = None
    if agent and agent.role not in OVERHEAD_ROLES:
        ticket = _resolve_ticket(db, agent, project.id)
        if ticket:
            sprint_id = ticket.sprint_id

    session = HookSession(
        session_id=session_id,
        transcript_path=transcript_path,
        agent_id=agent.id if agent else None,
        project_id=project.id,
        ticket_id=ticket.id if ticket else None,
        sprint_id=sprint_id,
        dwb_session_id=_active_dwb_session_id(db, project.id),
        status=HookSessionStatus.active,
        session_type=session_type,
        agent_name=agent_name,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Log start event through tracking.py
    if agent:
        if session_type in (HookSessionType.teammate, HookSessionType.subagent) and ticket:
            tracking.log_start(db, ticket.id, agent.id)
        elif session_type == HookSessionType.main or agent.role in OVERHEAD_ROLES:
            tracking.log_overhead_start(db, project.id, agent.id)

    # DWB-336: Layer-1 regex fast path for session-open detection. Run after
    # the hook_session is persisted so attribution stays correct even when
    # phrase detection no-ops. Errors are swallowed inside the helper.
    try_open_dwb_session_from_transcript(db, project, transcript_path)

    return session


def handle_session_end(db: Session, hook_data: dict) -> HookSession:
    """Handle a SessionEnd or SubagentStop hook event.

    SubagentStop events are detected and routed to _handle_subagent_stop()
    which creates a separate HookSession keyed on agent_id, NOT session_id.
    This avoids colliding with the parent TL session.

    SessionEnd events follow the existing flow unchanged.
    """
    # Detect SubagentStop — route to dedicated handler
    if hook_data.get("hook_event_name") == "SubagentStop" or (
        hook_data.get("agent_type") and hook_data.get("agent_id")
    ):
        return _handle_subagent_stop(db, hook_data)

    session_id = hook_data.get("session_id", "")
    if not session_id:
        raise ValueError("session_id is required")

    hook_event = hook_data.get("hook_event")
    transcript_path = hook_data.get("transcript_path")

    # Find existing or create new session
    session = db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )

    if session and session.status == HookSessionStatus.completed:
        # Already processed — idempotent
        return session

    # Parse transcript for tokens and timing
    token_total = 0
    token_breakdown = None
    end_time = datetime.now(UTC)

    if transcript_path:
        parsed = parse_transcript(transcript_path)
        token_total = parsed["total_tokens"]
        token_breakdown = parsed["breakdown"]
        if parsed.get("end_time"):
            end_time = parsed["end_time"]

    if not session:
        # Session-end arrived without a prior start — create it now
        cwd = hook_data.get("cwd", "")
        project = _resolve_project(db, cwd)
        if not project:
            raise ValueError(f"No project found for cwd: {cwd}")

        # Authoritative marker first (DWB-294).
        agent = resolve_agent_from_marker(
            db, project, session_id,
            hook_event=hook_event or hook_data.get("hook_event_name") or "SessionEnd",
            hook_data=hook_data,
        )
        agent_name: str | None = agent.name if agent else None

        if not agent:
            agent_name = hook_data.get("agent_name")
            if not agent_name and transcript_path:
                agent_name = _read_agent_name_from_transcript(transcript_path)
            agent = resolve_agent(db, agent_name, project.id) if agent_name else None

        # Main CLI session (no agent name) → attribute as TL overhead
        if not agent:
            agent = _fallback_tl_agent(db, project.id)
            if agent:
                agent_name = agent.role

        session_type = _determine_session_type(agent)

        ticket = None
        sprint_id = None
        if agent and agent.role not in OVERHEAD_ROLES:
            ticket = _resolve_ticket(db, agent, project.id)
            if ticket:
                sprint_id = ticket.sprint_id

        session = HookSession(
            session_id=session_id,
            transcript_path=transcript_path,
            agent_id=agent.id if agent else None,
            project_id=project.id,
            ticket_id=ticket.id if ticket else None,
            sprint_id=sprint_id,
            dwb_session_id=_active_dwb_session_id(db, project.id),
            status=HookSessionStatus.active,
            session_type=session_type,
            agent_name=agent_name,
        )
        db.add(session)
        db.flush()
    else:
        # Update transcript path if we have a better one
        if transcript_path and not session.transcript_path:
            session.transcript_path = transcript_path

        # DWB-373: Backfill dwb_session_id if SessionStart landed before the
        # enclosing DWB session opened. Only stamp on a still-NULL field so
        # we never reattribute a hook_session that already linked at start.
        if session.dwb_session_id is None:
            session.dwb_session_id = _active_dwb_session_id(db, session.project_id)

        # Re-resolve agent if we didn't get one at session start
        if not session.agent_id:
            agent = None
            agent_name = None
            # Authoritative marker first (DWB-294).
            project = db.get(Project, session.project_id)
            if project is not None:
                agent = resolve_agent_from_marker(
                    db, project, session_id,
                    hook_event=hook_event or hook_data.get("hook_event_name") or "SessionEnd",
                    hook_data=hook_data,
                )
                if agent:
                    agent_name = agent.name
            if not agent:
                if transcript_path:
                    agent_name = _read_agent_name_from_transcript(transcript_path)
                if agent_name:
                    agent = resolve_agent(db, agent_name, session.project_id)
            if agent_name:
                session.agent_name = agent_name
            # Still no agent? Fall back to TL
            if not agent:
                agent = _fallback_tl_agent(db, session.project_id)
                if agent:
                    session.agent_name = agent.role
            if agent:
                    session.agent_id = agent.id
                    session.session_type = _determine_session_type(agent)
                    # Resolve ticket if worker
                    if agent.role not in OVERHEAD_ROLES:
                        ticket = _resolve_ticket(db, agent, session.project_id)
                        if ticket:
                            session.ticket_id = ticket.id
                            session.sprint_id = ticket.sprint_id

    # Update session with end data
    session.end_time = end_time
    session.total_tokens = token_total
    session.token_breakdown = token_breakdown
    session.status = HookSessionStatus.completed
    session.hook_event = hook_event

    db.commit()
    db.refresh(session)

    # Log stop + tokens through tracking.py.
    #
    # DWB-353 routing:
    #   agent in OVERHEAD_ROLES (tl/pm)      -> overhead bucket (always, even with ticket)
    #   worker with ticket                   -> ticket attribution
    #   worker without ticket                -> ad_hoc bucket (was: silent tl overhead +
    #                                           unattributed alert; both removed)
    #   no agent at all                      -> nothing (silently dropped; the
    #                                           unattributed alert that used to fire
    #                                           here is dead per DWB-353)
    agent = db.get(Agent, session.agent_id) if session.agent_id else None
    if agent:
        if agent.role in OVERHEAD_ROLES:
            tracking.log_overhead_stop(db, session.project_id, agent.id)
            if token_total > 0:
                # log_overhead_tokens atomically updates the per-role bucket
                # on the project row - see DWB-305 / tracking.py.
                tracking.log_overhead_tokens(
                    db, session.project_id, agent.id, token_total, source="hook"
                )
        elif session.ticket_id:
            tracking.log_stop(db, session.ticket_id, agent.id)
            if token_total > 0:
                tracking.log_tokens(
                    db, session.ticket_id, agent.id, token_total, source="hook"
                )
                # Also increment the ticket's tokens_used field
                ticket = db.get(Ticket, session.ticket_id)
                if ticket:
                    ticket.tokens_used += token_total
                    ticket.token_source = "hook"
                    db.commit()
        else:
            # DWB-353: worker without ticket -> ad_hoc bucket. Previously this
            # silently inflated tl_overhead_tokens; the skip-ticket-overhead
            # lane is by design and shouldn't masquerade as TL work.
            tracking.log_ad_hoc_stop(db, session.project_id, agent.id)
            if token_total > 0:
                tracking.log_ad_hoc_tokens(
                    db, session.project_id, agent.id, token_total, source="hook"
                )

    # DWB-336: Layer-1 regex fast path for session-close detection. Same
    # post-commit timing as the open path so token attribution lands first.
    #
    # DWB-343: also run the OPEN regex retry here. Claude Code's SessionStart
    # hook fires ~2s before the user's first message hits the transcript JSONL,
    # so the Layer-1 open scan in handle_session_start frequently misses on the
    # very first hook of a session. By the time any Stop/SessionEnd/SubagentStop
    # fires (i.e., after the first assistant turn), the user's first message is
    # in the transcript and OPEN_PATTERNS can match. open_session no-ops
    # silently when a session is already open, so calling unconditionally is
    # safe and never disturbs a Layer-2 (ai_confident) open.
    if session.project_id:
        project = db.get(Project, session.project_id)
        if project is not None:
            try_close_dwb_session_from_transcript(db, project, transcript_path)
            try_open_dwb_session_from_transcript(db, project, transcript_path)

    return session


def _parse_transcript_lines(lines_iter, *, agent_name_filter: str | None = None) -> dict:
    """Shared transcript-line scanner. Sums usage entries; if
    agent_name_filter is set, only counts lines whose `agentName` matches.

    Returns the same shape as parse_transcript().
    """
    total = 0
    breakdown = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    last_timestamp = None

    for line in lines_iter:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # When filtering, only count lines tagged with the subagent's name.
        if agent_name_filter is not None and entry.get("agentName") != agent_name_filter:
            # Still let timestamps update — they bound the parent's wall time.
            ts = entry.get("timestamp")
            if ts:
                try:
                    last_timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass
            continue

        # Extract usage — nested under message.usage for assistant entries.
        usage = entry.get("message", {}).get("usage") or entry.get("usage")
        if usage:
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            cache_create = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            total += inp + out + cache_create + cache_read
            breakdown["input"] += inp
            breakdown["output"] += out
            breakdown["cache_creation"] += cache_create
            breakdown["cache_read"] += cache_read

        ts = entry.get("timestamp")
        if ts:
            try:
                last_timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

    return {
        "total_tokens": total,
        "breakdown": breakdown,
        "end_time": last_timestamp,
    }


def _parse_subagent_from_projects_dir(
    synthetic_path: str, agent_name: str
) -> dict:
    """DWB-311 fallback. When the SubagentStop hook payload's
    `agent_transcript_path` points at a synthetic path like
    `/projects/<project>/<parent_uuid>/subagents/agent-<sid>.jsonl` that
    doesn't actually exist on disk, walk the project's `.jsonl` siblings
    (the real per-session transcripts) and accumulate usage entries
    tagged with `agentName == agent_name`.

    Returns the same shape as parse_transcript(). On any failure or zero
    match, returns a zero result so the caller can continue normally.

    Path structure assumption (matches Claude Code's hook payload format
    as of 2026-06-05): `<synthetic>.parent.parent.parent` is the CC
    projects directory containing the real `*.jsonl` session files. If
    the layout ever changes, this returns zero and the symptom is
    "tokens not landing" — same observable as the pre-fix bug.
    """
    if not agent_name:
        return {"total_tokens": 0,
                "breakdown": {"input": 0, "output": 0,
                              "cache_creation": 0, "cache_read": 0},
                "end_time": None}

    try:
        projects_dir = Path(synthetic_path).parent.parent.parent
    except (ValueError, OSError):
        return {"total_tokens": 0,
                "breakdown": {"input": 0, "output": 0,
                              "cache_creation": 0, "cache_read": 0},
                "end_time": None}

    if not projects_dir.exists() or not projects_dir.is_dir():
        return {"total_tokens": 0,
                "breakdown": {"input": 0, "output": 0,
                              "cache_creation": 0, "cache_read": 0},
                "end_time": None}

    # Accumulate across all sibling jsonls. Most projects have just a
    # handful (one per CC session) and we want every matching line.
    aggregated_total = 0
    aggregated_breakdown = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    latest_timestamp = None

    for jsonl_path in projects_dir.glob("*.jsonl"):
        try:
            with jsonl_path.open("r") as fh:
                parsed = _parse_transcript_lines(fh, agent_name_filter=agent_name)
        except OSError as e:
            logger.warning(
                "DWB-311 fallback: could not read %s while looking for "
                "subagent agentName=%s: %s",
                jsonl_path, agent_name, e,
            )
            continue
        aggregated_total += parsed["total_tokens"]
        for k, v in parsed["breakdown"].items():
            aggregated_breakdown[k] += v
        if parsed.get("end_time"):
            if latest_timestamp is None or parsed["end_time"] > latest_timestamp:
                latest_timestamp = parsed["end_time"]

    return {
        "total_tokens": aggregated_total,
        "breakdown": aggregated_breakdown,
        "end_time": latest_timestamp,
    }


def parse_transcript(path: str) -> dict:
    """Parse a Claude Code JSONL transcript file for token usage and timing.

    Returns:
        {
            "total_tokens": int,
            "breakdown": {"input": int, "output": int, "cache_creation": int, "cache_read": int},
            "end_time": datetime | None,
        }
    """
    transcript = Path(path)
    if not transcript.exists():
        logger.warning("Transcript not found: %s", path)
        return {
            "total_tokens": 0,
            "breakdown": {"input": 0, "output": 0,
                          "cache_creation": 0, "cache_read": 0},
            "end_time": None,
        }

    try:
        with transcript.open("r") as f:
            return _parse_transcript_lines(f)
    except OSError:
        logger.warning("Could not read transcript: %s", path)
        return {
            "total_tokens": 0,
            "breakdown": {"input": 0, "output": 0,
                          "cache_creation": 0, "cache_read": 0},
            "end_time": None,
        }


def resolve_agent_from_marker(
    db: Session,
    project: Project,
    session_id: str,
    *,
    hook_event: str,
    hook_data: dict,
) -> Agent | None:
    """Read .claude/agents/active/<session_id> marker and resolve the agent.

    Returns the Agent on success, or None if the marker is missing,
    unparseable, or its agent_id doesn't resolve. On every failure, writes a
    FailedHook row with a specific reason so the diagnostic isn't silent.

    Resolution order:

      1. Strict literal lookup: <session_id> file. Used by main-CC sessions
         where the TL knows the session_id and can pre-write a matching
         marker, and by direct-write tests.
      2. DWB-304 pending-marker fallback: when the literal file is missing,
         scan for an unconsumed `pending-<agent_id>-<ms>-<rand>` marker that
         belongs to this project and atomically rename it to <session_id>.
         CC's SubagentStop session_ids are generated internally and can't be
         pre-computed by the TL, so the TL writes pending markers keyed on
         agent identity instead. The rename is the consume signal — os.rename
         is atomic, so concurrent SubagentStops can't double-claim.

         DWB-390: when the hook payload carries an agent identity hint
         (``agent_type`` / ``agent_name``), the scan filters candidates to
         the matching ``agent_id`` so concurrent SubagentStops from different
         agents can't race-claim each other's markers. Without a hint (older
         SessionStart paths, hooks fired before the TL writes a marker) the
         scan falls back to FIFO across all pending markers for this project.

    The marker file is authoritative when present: it skips the role/name
    resolve heuristics that historically lost attribution (the PM=50-tokens
    bug). When absent, callers fall back to the existing resolve_agent path.
    """
    if not project.repo_path or not session_id:
        return None

    marker_dir = Path(project.repo_path) / _SESSION_MARKER_SUBPATH
    marker_path = marker_dir / session_id

    # Step 1: strict literal lookup.
    if marker_path.is_file():
        return _read_marker_and_resolve(
            db, project, marker_path, session_id, hook_event,
        )

    # Step 2: pending-marker fallback (DWB-304 + DWB-390 agent_id-aware claim).
    agent_id_hint = _hint_agent_id_from_hook(db, project, hook_data)
    claimed = _claim_pending_marker(
        marker_dir, project.id, marker_path, hook_event,
        agent_id_hint=agent_id_hint,
    )
    if claimed:
        return _read_marker_and_resolve(
            db, project, marker_path, session_id, hook_event,
        )

    # Step 3: no marker — diagnostic + bow out.
    log_failed_hook(
        hook_event=hook_event,
        status_code=None,
        raw_payload={"session_id": session_id, "marker_path": str(marker_path)},
        error=f"marker_missing: no session marker at {marker_path}",
    )
    return None


def _read_marker_and_resolve(
    db: Session,
    project: Project,
    marker_path: Path,
    session_id: str,
    hook_event: str,
) -> Agent | None:
    """Read a marker file, look up its agent, and project-guard the result.

    Shared by both the strict-literal and pending-fallback paths so the
    JSON parse + agent lookup + project guard logic stays in one place.
    """
    try:
        raw = marker_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
        if not isinstance(data, dict) or "agent_id" not in data:
            raise ValueError("marker missing 'agent_id' field")
        agent_id = int(data["agent_id"])
    except (OSError, ValueError, TypeError) as e:
        log_failed_hook(
            hook_event=hook_event,
            status_code=None,
            raw_payload={"session_id": session_id, "marker_path": str(marker_path)},
            error=f"marker_unparseable: {type(e).__name__}: {e}",
        )
        return None

    agent = db.get(Agent, agent_id)
    if agent is None:
        log_failed_hook(
            hook_event=hook_event,
            status_code=None,
            raw_payload={"session_id": session_id, "marker_agent_id": agent_id},
            error=f"marker_agent_unknown: agent_id={agent_id} not found",
        )
        return None
    if agent.project_id is not None and agent.project_id != project.id:
        log_failed_hook(
            hook_event=hook_event,
            status_code=None,
            raw_payload={
                "session_id": session_id,
                "marker_agent_id": agent_id,
                "marker_project_id": project.id,
                "agent_project_id": agent.project_id,
            },
            error=(
                f"marker_project_mismatch: agent {agent_id} belongs to "
                f"project {agent.project_id}, marker fired in project {project.id}"
            ),
        )
        return None
    return agent


def _hint_agent_id_from_hook(
    db: Session, project: Project, hook_data: dict
) -> int | None:
    """DWB-390: pull the agent_id hint out of a hook payload for the pending-
    marker claim filter.

    SubagentStop payloads include ``agent_type`` (the role/name CC matched on
    when spawning the subagent). SessionStart/SessionEnd payloads may include
    ``agent_name`` when the caller pre-fills it. Either is enough to resolve
    one Agent row inside this project; we then filter the pending-marker scan
    to that agent_id so a concurrent stop from a sibling agent can't claim
    this agent's marker.

    Returns the Agent.id when the hook payload identifies exactly one matching
    agent in this project; returns None when the payload carries no hint or
    the hint doesn't resolve (caller falls back to FIFO behavior).
    """
    name = hook_data.get("agent_type") or hook_data.get("agent_name")
    if not name or not isinstance(name, str) or not name.strip():
        return None
    agent = resolve_agent(db, name, project.id)
    return agent.id if agent else None


def _claim_pending_marker(
    marker_dir: Path,
    project_id: int,
    target_path: Path,
    hook_event: str,
    *,
    agent_id_hint: int | None = None,
) -> bool:
    """Find an unconsumed pending-* marker for this project and rename it to
    `target_path` (the actual SubagentStop session_id). Returns True if a
    marker was successfully claimed, False otherwise.

    Selection rules:

      - When ``agent_id_hint`` is provided (DWB-390), the scan considers only
        candidates whose marker JSON's ``agent_id`` equals the hint. The
        oldest such candidate wins by unix_ms. If no candidate matches the
        hint, no claim is made: better to fall through to the legacy
        resolve_agent path than to misattribute by stealing a sibling agent's
        marker.
      - When ``agent_id_hint`` is None (older hook paths, payloads with no
        identity hint), the scan falls back to FIFO across every project-
        matching pending marker. This preserves the DWB-304 single-pending
        behavior.

    Lazy garbage-collection: any pending marker older than
    `_PENDING_MARKER_STALE_SECONDS` (mtime-based) is unlinked during the scan.

    Race safety: os.rename is atomic on POSIX. If two SubagentStops fire at
    the same moment, only one rename succeeds for any given pending marker;
    the loser gets FileNotFoundError and proceeds to the next-oldest candidate.

    Project safety: each pending marker's JSON is read and its `project_id`
    must match `project.id`, so a stale marker from a different project can't
    be erroneously consumed.
    """
    if not marker_dir.is_dir():
        return False

    now = time.time()
    candidates: list[tuple[int, Path]] = []  # (unix_ms_from_filename, path)

    try:
        entries = list(marker_dir.iterdir())
    except OSError:
        return False

    for entry in entries:
        m = _PENDING_MARKER_RE.match(entry.name)
        if not m:
            continue

        # Staleness check — unlink and skip. Use mtime rather than filename ms
        # so a clock-skewed filename can still be GC'd.
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) > _PENDING_MARKER_STALE_SECONDS:
            try:
                entry.unlink()
            except OSError:
                pass
            continue

        # Project guard — read the JSON, drop markers that don't belong here.
        try:
            data = json.loads(entry.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, TypeError):
            # Unparseable markers are NOT claimable; we don't want to
            # claim-then-fail-to-parse and orphan the rename. Skip.
            continue
        if not isinstance(data, dict):
            continue
        marker_pid = data.get("project_id")
        if marker_pid is not None and int(marker_pid) != project_id:
            continue

        # DWB-390 agent-aware claim: when the hook payload identifies one
        # specific agent, only that agent's pending markers are eligible.
        # Without a hint, every pending marker for this project is fair game
        # (legacy FIFO path).
        if agent_id_hint is not None:
            marker_aid = data.get("agent_id")
            try:
                marker_aid_int = int(marker_aid) if marker_aid is not None else None
            except (TypeError, ValueError):
                marker_aid_int = None
            if marker_aid_int != agent_id_hint:
                continue

        unix_ms = int(m.group(2))
        candidates.append((unix_ms, entry))

    # Oldest unix_ms first → that's the spawn the TL kicked off first.
    candidates.sort(key=lambda t: t[0])

    for _, pending_path in candidates:
        try:
            os.rename(pending_path, target_path)
        except FileNotFoundError:
            # Another resolver instance already claimed this marker.
            continue
        except OSError as e:
            # Treat any other rename failure as a hard miss for this marker
            # but keep trying the next-oldest.
            log_failed_hook(
                hook_event=hook_event,
                status_code=None,
                raw_payload={
                    "pending_path": str(pending_path),
                    "target_path": str(target_path),
                },
                error=f"pending_claim_rename_failed: {type(e).__name__}: {e}",
            )
            continue
        return True

    return False


def resolve_agent(db: Session, agent_name: str | None, project_id: int) -> Agent | None:
    """Resolve an agent from the transcript agent name.

    1. Match by agent.role == agent_name (primary — roles match teammate names)
    2. Fallback to agent.name match
    3. Scoped to project assignments via project_agents table
    """
    if not agent_name:
        return None

    # Get agent IDs assigned to this project
    assigned_ids = list(db.scalars(
        select(ProjectAgent.agent_id)
        .where(ProjectAgent.project_id == project_id)
    ).all())

    if not assigned_ids:
        return None

    # Primary: match by role (teammate names map to roles)
    agent = db.scalar(
        select(Agent)
        .where(Agent.id.in_(assigned_ids))
        .where(Agent.role == agent_name)
    )
    if agent:
        return agent

    # Fallback: match by name (case-insensitive)
    agent = db.scalar(
        select(Agent)
        .where(Agent.id.in_(assigned_ids))
        .where(Agent.name.ilike(agent_name))
    )
    if not agent:
        logger.warning(
            "resolve_agent: no match for agent_name=%r in project %d "
            "(Teams agentName may not match DWB agent role/name)",
            agent_name, project_id,
        )
    return agent


def list_sessions(
    db: Session,
    project_id: int | None = None,
    status: HookSessionStatus | None = None,
) -> list[HookSession]:
    """List hook sessions with optional filters."""
    stmt = select(HookSession)
    if project_id is not None:
        stmt = stmt.where(HookSession.project_id == project_id)
    if status is not None:
        stmt = stmt.where(HookSession.status == status)
    stmt = stmt.order_by(HookSession.created_at.desc())
    return list(db.scalars(stmt).all())


def list_orphan_sessions(
    db: Session,
    project_id: int | None = None,
    cutoff_minutes: int = 30,
) -> list[tuple[HookSession, int]]:
    """Active hook sessions whose start_time is older than `cutoff_minutes`.

    Returns (session, elapsed_seconds) tuples so the diagnostic endpoint can
    surface elapsed time without re-walking timestamps client-side.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.utcnow() - timedelta(minutes=cutoff_minutes)
    stmt = (
        select(HookSession)
        .where(HookSession.status == HookSessionStatus.active)
        .where(HookSession.start_time < cutoff)
    )
    if project_id is not None:
        stmt = stmt.where(HookSession.project_id == project_id)
    stmt = stmt.order_by(HookSession.start_time.asc())
    rows = list(db.scalars(stmt).all())

    now = datetime.utcnow()
    paired: list[tuple[HookSession, int]] = []
    for row in rows:
        # HookSession.start_time is stored as naive UTC; subtract naive `now`.
        elapsed = int((now - row.start_time).total_seconds())
        paired.append((row, elapsed))
    return paired


def get_session(db: Session, session_id: str) -> HookSession | None:
    """Get a single hook session by its Claude Code session_id."""
    return db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )


def _handle_subagent_stop(db: Session, hook_data: dict) -> HookSession:
    """Handle a SubagentStop hook event — creates a separate teammate session.

    SubagentStop sends agent_id (unique per subagent), agent_type (teammate
    role/name), and agent_transcript_path (subagent-specific transcript).
    The session_id in SubagentStop is the PARENT session — we must NOT
    look it up or modify it.
    """
    subagent_id = hook_data.get("agent_id", "")
    if not subagent_id:
        raise ValueError("agent_id is required for SubagentStop")

    # Idempotent: check if we already processed this subagent
    existing = db.scalar(
        select(HookSession).where(HookSession.session_id == subagent_id)
    )
    if existing and existing.status == HookSessionStatus.completed:
        return existing

    # Parse the subagent's transcript (NOT the parent's)
    agent_transcript_path = hook_data.get("agent_transcript_path")
    token_total = 0
    token_breakdown = None
    end_time = datetime.now(UTC)

    if agent_transcript_path:
        parsed = parse_transcript(agent_transcript_path)
        token_total = parsed["total_tokens"]
        token_breakdown = parsed["breakdown"]
        if parsed.get("end_time"):
            end_time = parsed["end_time"]

    # Resolve project from cwd
    cwd = hook_data.get("cwd", "")
    project = _resolve_project(db, cwd)
    if not project:
        raise ValueError(f"No project found for cwd: {cwd}")

    # 1. Authoritative marker — keyed on subagent_id (DWB-294).
    agent = resolve_agent_from_marker(
        db, project, subagent_id,
        hook_event=hook_data.get("hook_event_name") or "SubagentStop",
        hook_data=hook_data,
    )

    # 2. Fallback to legacy agent_type resolve.
    agent_type = hook_data.get("agent_type")
    if not agent:
        agent = resolve_agent(db, agent_type, project.id) if agent_type else None

    # If still nothing (e.g. "Explore" subagent), attribute to the TL as overhead
    if not agent:
        agent = _fallback_tl_agent(db, project.id)

    # DWB-311 — primary parse returned zero AND the synthetic agent_transcript_path
    # doesn't exist on disk. This is the production failure mode: Claude Code's
    # SubagentStop hook reports `<projects>/<x>/<parent_uuid>/subagents/agent-<sid>.jsonl`
    # but that file is never written; the subagent's tokens are interleaved in
    # the parent session's top-level .jsonl tagged with `agentName`. Walk the
    # project's .jsonl siblings filtering by the resolved agent's name.
    if (
        token_total == 0
        and agent_transcript_path
        and not Path(agent_transcript_path).exists()
        and agent
    ):
        fallback = _parse_subagent_from_projects_dir(
            agent_transcript_path, agent.name
        )
        if fallback["total_tokens"] > 0:
            token_total = fallback["total_tokens"]
            token_breakdown = fallback["breakdown"]
            if fallback.get("end_time"):
                end_time = fallback["end_time"]

    session_type = _determine_session_type(agent)

    # Resolve work context for workers
    ticket = None
    sprint_id = None
    if agent and agent.role not in OVERHEAD_ROLES:
        ticket = _resolve_ticket(db, agent, project.id)
        if ticket:
            sprint_id = ticket.sprint_id

    if existing:
        # Update the existing active session
        session = existing
        session.agent_id = agent.id if agent else None
        session.ticket_id = ticket.id if ticket else None
        session.sprint_id = sprint_id
        session.session_type = session_type
        session.agent_name = agent_type
        # DWB-373: Backfill dwb_session_id if the subagent_id row was
        # created before any DWB session opened. Only stamp on NULL.
        if session.dwb_session_id is None:
            session.dwb_session_id = _active_dwb_session_id(db, session.project_id)
    else:
        # Create new session keyed on subagent_id
        session = HookSession(
            session_id=subagent_id,
            transcript_path=agent_transcript_path,
            agent_id=agent.id if agent else None,
            project_id=project.id,
            ticket_id=ticket.id if ticket else None,
            sprint_id=sprint_id,
            dwb_session_id=_active_dwb_session_id(db, project.id),
            status=HookSessionStatus.active,
            session_type=session_type,
            agent_name=agent_type,
        )
        db.add(session)
        db.flush()

    # Mark completed with token data
    session.end_time = end_time
    session.total_tokens = token_total
    session.token_breakdown = token_breakdown
    session.status = HookSessionStatus.completed
    session.hook_event = "SubagentStop"

    db.commit()
    db.refresh(session)

    # Log stop + tokens through tracking.py.
    # DWB-353 routing: same as handle_session_end (see comments there).
    if agent:
        if agent.role in OVERHEAD_ROLES:
            tracking.log_overhead_stop(db, session.project_id, agent.id)
            if token_total > 0:
                tracking.log_overhead_tokens(
                    db, session.project_id, agent.id, token_total, source="hook"
                )
        elif session.ticket_id:
            tracking.log_stop(db, session.ticket_id, agent.id)
            if token_total > 0:
                tracking.log_tokens(
                    db, session.ticket_id, agent.id, token_total, source="hook"
                )
                # Also increment the ticket's tokens_used field
                ticket = db.get(Ticket, session.ticket_id)
                if ticket:
                    ticket.tokens_used += token_total
                    ticket.token_source = "hook"
                    db.commit()
        else:
            tracking.log_ad_hoc_stop(db, session.project_id, agent.id)
            if token_total > 0:
                tracking.log_ad_hoc_tokens(
                    db, session.project_id, agent.id, token_total, source="hook"
                )

    return session


# --- Internal helpers ---


def _resolve_project(db: Session, cwd: str) -> Project | None:
    """Match a working directory to a project by repo_path."""
    if not cwd:
        return None

    # Exact match first
    project = db.scalar(
        select(Project).where(Project.repo_path == cwd)
    )
    if project:
        return project

    # Prefix match — cwd may be a subdirectory of repo_path
    projects = list(db.scalars(
        select(Project).where(Project.repo_path.isnot(None))
    ).all())
    for p in projects:
        if p.repo_path and cwd.startswith(p.repo_path):
            return p

    return None


def _read_agent_name_from_transcript(path: str) -> str | None:
    """Quick-read the first few lines of a transcript for agentName."""
    transcript = Path(path)
    if not transcript.exists():
        return None

    try:
        with transcript.open("r") as f:
            for i, line in enumerate(f):
                if i > 20:  # Only check first 20 lines
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    agent_name = entry.get("agentName")
                    if agent_name:
                        return agent_name
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return None


def _fallback_tl_agent(db: Session, project_id: int) -> Agent | None:
    """Find the team-lead agent assigned to a project.

    Used as fallback when a main CLI session has no agent name — the human
    user running Claude Code directly is effectively the TL.
    """
    return db.scalar(
        select(Agent)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == "team-lead")
        .limit(1)
    )


def _determine_session_type(agent: Agent | None) -> HookSessionType:
    """Determine session type from agent role."""
    if not agent:
        return HookSessionType.main
    if agent.role in OVERHEAD_ROLES:
        return HookSessionType.main
    return HookSessionType.teammate


def _resolve_ticket(db: Session, agent: Agent, project_id: int) -> Ticket | None:
    """Find the best ticket to attribute work to for a worker agent.

    Priority:
    1. In-progress ticket assigned to this agent
    2. Todo ticket assigned to this agent (most recently updated)
    3. In-review ticket assigned to this agent (most recently updated)
    4. Done ticket assigned to this agent (only if updated within last 5 minutes)
    5. None (unattributed)
    """
    # In-progress ticket assigned to this agent
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.in_progress)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    if ticket:
        return ticket

    # Fallback: todo ticket assigned to this agent
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.todo)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    if ticket:
        return ticket

    # Fallback: in_review ticket assigned to this agent
    # Workers move tickets to in_review before session ends, so SubagentStop
    # often fires after the status change.
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.in_review)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    if ticket:
        return ticket

    # Fallback: recently-done ticket assigned to this agent (within 5 minutes)
    # Catches cases where TL accepts a ticket quickly before SubagentStop fires.
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.done)
        .where(Ticket.updated_at >= cutoff)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    return ticket


# ---------------------------------------------------------------------------
# DWB session phrase detection (DWB-336)
#
# Layer 1 of session lifecycle: when a hook fires, we peek the user-side
# messages in the transcript and try to match the regex catalogue in
# app.config.session_phrases. If we hit an open phrase and the project has
# no active DWB session, we open one. If we hit a close phrase and an active
# session exists, we close it. Both paths swallow all exceptions — hooks
# are fire-and-forget; phrase detection must never block ticket attribution.
# ---------------------------------------------------------------------------


# Cap on how many user messages we scan from a transcript. Open phrases live
# in the first user turn; close phrases live in the last few user turns.
# 50 entries is generous and bounds the worst-case JSONL read.
_PHRASE_SCAN_LIMIT = 50


def _extract_user_message_texts(path: str, *, head: bool) -> list[str]:
    """Return user-side message texts from a Claude Code JSONL transcript.

    Claude Code stores each turn as a JSON line. User turns look like:

        {"type": "user", "message": {"role": "user", "content": "..."},
         "timestamp": "..."}

    or with structured content:

        {"type": "user", "message": {"role": "user",
         "content": [{"type": "text", "text": "..."}]}, ...}

    ``head=True`` returns the first ``_PHRASE_SCAN_LIMIT`` lines that decode
    as user messages (used for open-phrase detection on SessionStart).
    ``head=False`` returns the last ``_PHRASE_SCAN_LIMIT`` (used for close
    detection on SessionEnd). Both bound I/O.

    Returns an empty list on any read/parse error.
    """
    transcript = Path(path)
    if not transcript.exists():
        return []

    try:
        with transcript.open("r") as fh:
            lines = fh.readlines()
    except OSError:
        return []

    iter_lines = lines if head else list(reversed(lines))

    out: list[str] = []
    for raw in iter_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue

        # Identify user turns. CC's format puts role on the inner message,
        # but historical/test fixtures sometimes flatten role/type to top
        # level. Accept both.
        msg = entry.get("message") or {}
        is_user = (
            entry.get("type") == "user"
            or msg.get("role") == "user"
            or entry.get("role") == "user"
        )
        if not is_user:
            continue

        content = msg.get("content") or entry.get("content")
        text: str | None = None
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # Structured content: concatenate every text block.
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    val = block.get("text")
                    if isinstance(val, str):
                        parts.append(val)
            if parts:
                text = "\n".join(parts)

        if text:
            out.append(text)
        if len(out) >= _PHRASE_SCAN_LIMIT:
            break

    return out


def try_open_dwb_session_from_transcript(
    db: Session, project: Project, transcript_path: str | None
) -> None:
    """Layer-1 regex fast path: scan early user turns for an open phrase and,
    on match, open a DWB session for the project via the service layer.

    No-op if:
      - transcript_path is missing or unreadable
      - no user message matches an OPEN_PATTERNS regex
      - the project already has an open DWB session

    All exceptions are swallowed + logged as failed_hook rows. Hook flows
    must never raise out of this function — they're called in fire-and-
    forget paths and an exception here would break token attribution.
    """
    if not transcript_path:
        return
    try:
        texts = _extract_user_message_texts(transcript_path, head=True)
        for text in texts:
            phrase = match_open(text)
            if not phrase:
                continue
            # Found a match — try to open. The service returns (None,
            # existing) when a session is already open; that's a silent
            # no-op for the hook path (Layer 2 / explicit endpoint will
            # surface conflicts to the user).
            new_session, _existing = dwb_svc.open_session(
                db,
                project_id=project.id,
                opened_at=datetime.now(UTC),
                open_method=DwbOpenMethod.regex,
                open_phrase=phrase,
            )
            if new_session is not None:
                db.commit()
            return
    except Exception as e:
        logger.exception(
            "try_open_dwb_session_from_transcript failed for project_id=%s",
            project.id,
        )
        log_failed_hook(
            hook_event="dwb_session_open_regex",
            status_code=None,
            raw_payload={"project_id": project.id, "transcript_path": transcript_path},
            error=f"{type(e).__name__}: {e}",
        )


def try_close_dwb_session_from_transcript(
    db: Session, project: Project, transcript_path: str | None
) -> None:
    """Layer-1 regex fast path: scan late user turns for a close phrase and,
    on match, close the project's active DWB session via the service layer.

    No-op if:
      - transcript_path is missing or unreadable
      - no user message matches a CLOSE_PATTERNS regex
      - the project has no active DWB session

    Same exception-swallowing contract as
    ``try_open_dwb_session_from_transcript``: hooks never raise.
    """
    if not transcript_path:
        return
    try:
        texts = _extract_user_message_texts(transcript_path, head=False)
        for text in texts:
            phrase = match_close(text)
            if not phrase:
                continue
            active = dwb_svc.get_active_session(db, project.id)
            if active is None:
                return
            dwb_svc.close_session(
                db,
                active,
                close_method=DwbCloseMethod.regex,
                close_reason=DwbCloseReason.explicit,
                close_phrase=phrase,
            )
            db.commit()
            return
    except Exception as e:
        logger.exception(
            "try_close_dwb_session_from_transcript failed for project_id=%s",
            project.id,
        )
        log_failed_hook(
            hook_event="dwb_session_close_regex",
            status_code=None,
            raw_payload={"project_id": project.id, "transcript_path": transcript_path},
            error=f"{type(e).__name__}: {e}",
        )


def handle_user_prompt(
    db: Session,
    hook_data: dict,
) -> dict:
    """Handle a UserPromptSubmit hook event (DWB-344, DWB-377).

    The fastest available path for phrase-driven session lifecycle: Claude Code
    fires UserPromptSubmit synchronously as the user submits a message and
    includes the raw prompt text in the payload, so we match against
    ``match_open(prompt)`` / ``match_close(prompt)`` directly without scanning
    the transcript.

    Why this exists: the SessionStart / SessionEnd hooks lag the user's first
    and last messages by a turn each (SessionStart fires before the message
    lands in the transcript; SessionEnd never fires until the next session
    starts), so the Layer-1 transcript-scan path (DWB-336) misses the initial
    open AND lets idle_timeout be the only path that closes a session whose
    user explicitly said "shut down for the night". DWB-343 retries opens on
    SessionEnd; DWB-344 is the instant-open sibling; DWB-377 mirrors DWB-344
    on the close side.

    Path order:

      1. ``prompt`` missing/empty                  -> noop reason=no_prompt
      2. ``cwd`` does not resolve to a project     -> noop reason=no_project_for_cwd
      3. ``match_open(prompt)`` hits:
         - active session already open            -> noop reason=already_open
         - else                                   -> open via open_session, return opened
      4. ``match_close(prompt)`` hits:
         - no active session                      -> noop reason=no_active_session
         - else                                   -> close via close_session, return closed
      5. neither matches                          -> noop reason=no_phrase_match

    DWB-402 (2026-06-19): the Layer-2 Haiku AI classifier fallback (DWB-382)
    was retired. When both regex ladders miss, this returns a plain noop; the
    deterministic ``/dwb-open`` / ``/dwb-close`` slash commands, the passive
    regex layer, and the idle sweeper are the remaining lifecycle paths. The
    ``ai_classifier`` open/close-method enum values are kept as legacy
    tombstones so historical rows still load, but nothing produces new ones.

    Privacy (DWB-351): both ``open_phrase`` and ``close_phrase`` on Layer-1
    are the matched catalogued substrings from ``app.config.session_phrases``
    (hardcoded text), NOT free-form user input. Persisting them is safe; the
    raw ``prompt`` is matched in-memory and never logged or stored. The
    exception-path scrub below redacts ``prompt`` from the raw_payload before
    forwarding to log_failed_hook.

    Fire-and-forget: every exception is swallowed and logged to failed_hooks.
    Returns a small status dict either way; the router always returns 200.
    """
    try:
        prompt = hook_data.get("prompt")
        if not prompt:
            return {"status": "noop", "reason": "no_prompt"}

        cwd = hook_data.get("cwd", "")
        project = _resolve_project(db, cwd)
        if not project:
            return {"status": "noop", "reason": "no_project_for_cwd"}

        # ---- Open path (DWB-344) ----
        open_phrase = match_open(prompt)
        if open_phrase:
            # Single-active guard: defer to open_session for the actual
            # race-safe check, but short-circuit here so the common case
            # doesn't churn the transaction.
            if dwb_svc.get_active_session(db, project.id) is not None:
                return {"status": "noop", "reason": "already_open"}

            new_session, _existing = dwb_svc.open_session(
                db,
                project_id=project.id,
                opened_at=datetime.now(UTC),
                open_method=DwbOpenMethod.regex,
                open_phrase=open_phrase,
            )
            if new_session is None:
                # Lost the race; another caller opened concurrently.
                return {"status": "noop", "reason": "already_open"}
            db.commit()
            return {
                "status": "opened",
                "dwb_session_id": new_session.id,
                "open_phrase": open_phrase,
            }

        # ---- Close path (DWB-377) ----
        close_phrase = match_close(prompt)
        if close_phrase:
            active = dwb_svc.get_active_session(db, project.id)
            if active is None:
                return {"status": "noop", "reason": "no_active_session"}
            # close_session is idempotent: if another path (sweeper, explicit
            # endpoint) closed the row between our get_active_session and
            # here, the second call returns the row unchanged. The check
            # `active.closed_at is not None` after the fact lets us surface
            # the race as a noop instead of falsely advertising a close.
            dwb_svc.close_session(
                db,
                active,
                close_method=DwbCloseMethod.regex,
                close_reason=DwbCloseReason.explicit,
                close_phrase=close_phrase,
            )
            db.commit()
            return {
                "status": "closed",
                "dwb_session_id": active.id,
                "close_phrase": close_phrase,
            }

        # ---- Neither ladder matched ----
        # DWB-402: the Layer-2 Haiku AI classifier fallback (DWB-382) was
        # retired. A non-matching prompt is simply a noop; the deterministic
        # slash commands, regex layer, and idle sweeper cover the rest.
        return {"status": "noop", "reason": "no_phrase_match"}
    except Exception as e:
        # DWB-351 privacy: the user's prompt is matched in-memory and must
        # NOT be persisted under any circumstance. Strip it from the raw
        # payload before forwarding to log_failed_hook (failed_hooks.raw_payload
        # would otherwise capture it on every UserPromptSubmit exception).
        # The logger.exception line below intentionally does NOT interpolate
        # the prompt; the stack trace alone is enough to debug a hook crash.
        scrubbed = {k: v for k, v in hook_data.items() if k != "prompt"}
        if "prompt" in hook_data:
            scrubbed["prompt"] = "<redacted>"
        logger.exception("handle_user_prompt failed")
        log_failed_hook(
            hook_event=hook_data.get("hook_event_name") or "UserPromptSubmit",
            status_code=None,
            raw_payload=scrubbed,
            error=f"{type(e).__name__}: {e}",
        )
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}


# DWB-353: _create_unattributed_alert was deleted along with its two call
# sites in handle_session_end and handle_subagent_stop. The "unattributed"
# alert class is gone - worker-without-ticket tokens now flow into the
# ad_hoc bucket (see DWB-353 in tracking.py); no-agent-at-all sessions
# silently drop their tokens (rare; not worth paging on).
