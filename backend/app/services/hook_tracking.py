# Path: app/services/hook_tracking.py
# File: hook_tracking.py
# Created: 2026-04-09
# Purpose: Hook-based tracking service - handles Claude Code lifecycle hook events + DWB session phrase detection (DWB-336 Layer-1 regex, DWB-343 OPEN retry on session-end, DWB-344 UserPromptSubmit fast path, DWB-353 ad_hoc routing + alert removal, DWB-373 hook_session.dwb_session_id linker, DWB-390 agent-id-aware pending-marker claim, DWB-395 grace-window resurrect, DWB-402 Layer-2 Haiku classifier retired)
# Caller: app/routers/hooks.py
# Callees: app/models/hook_session.py, app/models/tool_action.py, app/services/tracking.py, app/services/dwb_session.py, app/services/activity_log.py, app/models/alert.py, app/config/session_phrases.py, app/services/journal.py (DWB-612 top-off journal search), app/services/memory_consult.py (DWB-612 top-off scar consult), app/services/memory_consolidate.py (DWB-609 session-start consolidation)
# Data In: db: Session, hook event JSON from Claude Code hooks
# Data Out: HookSession records, ToolAction records (DWB-417..421), activity-feed verbs, tracking_log events via tracking.py, opened/closed/reopened DwbSession rows, memory movements via memory_consolidate (DWB-609)
# Last Modified: 2026-10-06 (top-off is suppressed while a memory transition is
#                in flight: the firing pass promotes a scar to CORE at a
#                threshold, and during adopting/reverting the store is partial,
#                so it would reach the one tier `decide` refuses an agent on
#                evidence from a catalogue that is still mostly in the old file;
#                previous entry: DWB-634: start_time and end_time normalised to
#                second precision at the transcript ingest boundary, so the
#                column stops carrying two conventions; previous entry:
#                DWB-612 top-off's firing pass also consults scars
#                via memory_consult.consult_scars, same term as the journal
#                search, per Miles's "same pass, same term" ruling; previous
#                entry: DWB-609 handle_session_start consolidation)
#
# DWB-417 (2026-06-22): handle_tool_use ingests the PostToolUse hook and
# persists one tool_actions row per tool call, resolving agent/dwb_session/
# ticket context from session_id the same way handle_session_end does (existing
# hook_session -> authoritative marker -> _resolve_ticket / _active_dwb_session_id).
# Foundation for the agent-scoring epic; stored the generic event only.
# DWB-418..421 (2026-06-22): per-tool classification on top of that foundation -
# file_written (Write/Edit/MultiEdit/NotebookEdit), message_sent (SendMessage,
# recipient only - no body), agent_spawned (Task), plus the Notification /
# PreCompact lifecycle events via handle_lifecycle_event. Classified events emit
# a semantic activity-feed verb (entity_type="tool_action"); the generic
# 'tool_use' fallback does not (feed-noise control).
#
# DWB-414 (2026-06-22): scope session phrase detection to genuine user-authored
# turns. _extract_user_message_texts now drops non-human user-role entries
# (isMeta, tool-result echoes, and string content beginning with a synthetic
# wrapper tag: teammate-message, command echo/stdout, task-notification,
# system-reminder, ...) and handle_user_prompt skips a synthetic-wrapped prompt.
# Fixes false closes from close phrases quoted in injected/example text
# (DWB-396). Matched in-memory only; no user text persisted (DWB-351).
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

from app.config import settings
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
from app.models.hook_session import (
    TICKET_SOURCE_CLAIMED_BY_TICKET,
    TICKET_SOURCE_RESOLVED_AT_START,
    TICKET_SOURCE_RESOLVED_LATER,
    HookSession,
    HookSessionStatus,
    HookSessionType,
)
from app.models.project import MemoryMode, Project
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.inter_agent_message import InterAgentMessage
from app.models.ticket import Ticket, TicketStatus
from app.models.tool_action import ToolAction
from app.services import dwb_session as dwb_svc
from app.services import journal as journal_svc
from app.services import memory_consolidate
from app.services import memory_consult
from app.services import timestamps
from app.services import tracking
from app.services.activity_log import log_activity
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
    8. DWB-609: run the memory consolidation job (human_memory projects,
       resolved agent only; never fails the hook)
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
        ticket_source=TICKET_SOURCE_RESOLVED_AT_START if ticket else None,
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

    # DWB-609: the session-start consolidation job. Gated on human_memory
    # mode and a resolved agent - a project in stock mode has no agent_memories
    # rows to consolidate, and a session with no resolved agent (main CLI
    # overhead, an unmatched name) has nothing to run it for. Never allowed to
    # fail the hook: this endpoint must never 5xx (module docstring, hooks.py),
    # and a consolidation bug is not a reason to lose session-start tracking,
    # which has already succeeded by this point. Runs AT session start, which
    # is precisely the moment Miles ruled is NOT a read - every function this
    # calls into (see memory_consolidate.py) already avoids any fired_count /
    # retrieval_count write site, so this call cannot fire anything by
    # construction, not by remembering to pass a flag.
    if agent is not None and project.memory_mode == MemoryMode.human_memory:
        try:
            memory_consolidate.consolidate_agent(db, agent_id=agent.id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "DWB-609 consolidation failed for agent_id=%s session_id=%s",
                agent.id, session_id,
            )

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

    # DWB-580: the same freeze existed here. Removing it only on the
    # SubagentStop path would leave an identical copy to diverge, which is the
    # failure this ticket already has two instances of. Re-processing is safe
    # now for the same reason: record_session_tokens diffs against the stored
    # total, so a repeat delivery logs a delta of zero rather than a duplicate.

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
            ticket_source=TICKET_SOURCE_RESOLVED_AT_START if ticket else None,
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

        # DWB-576: re-resolve the TICKET on any later event while it is still
        # NULL, not only on the events where the AGENT also needed resolving.
        #
        # This lookup used to live nested inside `if not session.agent_id:`.
        # The marker resolves the agent correctly at row creation, so that
        # branch essentially never ran again and ticket resolution was
        # effectively one-shot: it asked "what ticket is this agent on" at the
        # instant the row was created and never asked again. On 2026-09-16 the
        # rows were created 15:07-15:15 and every ticket was assigned at
        # 15:32, so the question was asked 17 to 25 minutes before the answer
        # existed, and five of six workers' whole sessions fell to overhead.
        #
        # Fill-only, deliberately: a session that already carries a ticket is
        # never re-pointed at another one. Re-attributing finished work is a
        # worse failure than leaving it unattributed, because it moves a cost
        # that someone may already have read.
        if session.ticket_id is None and session.agent_id:
            resolved_agent = db.get(Agent, session.agent_id)
            if resolved_agent and resolved_agent.role not in OVERHEAD_ROLES:
                later_ticket = _resolve_ticket(
                    db, resolved_agent, session.project_id
                )
                if later_ticket:
                    session.ticket_id = later_ticket.id
                    session.sprint_id = later_ticket.sprint_id
                    session.ticket_source = TICKET_SOURCE_RESOLVED_LATER

    # Update session with end data
    # DWB-539: never persist end < start; a backwards interval clamps to 0 in
    # the rollup and reads as "worked no time" for a token-heavy session.
    if (
        session.start_time is not None
        and _as_naive_utc(end_time) < _as_naive_utc(session.start_time)
    ):
        logger.warning(
            "DWB-539: session %s transcript end %s precedes start %s; "
            "clamping to a zero-length interval",
            session.session_id, end_time, session.start_time,
        )
        end_time = session.start_time
    # DWB-634: second precision at ingest. start_time on this row may have come
    # from the server default (which truncates), so an end_time carrying a
    # fraction would round UP and inflate the interval by up to a second
    # against a floored start.
    session.end_time = timestamps.naive_utc_second(end_time)
    # DWB-580: total_tokens / token_breakdown are NOT set here. The recorder
    # below needs the previously stored total to compute a delta against;
    # stamping the new cumulative figure first makes every delta zero.
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
    # DWB-580: one shared recorder for both entry points and the sweeper. It
    # owns the cumulative-vs-delta rule and the DWB-353 bucket routing.
    delta = record_session_tokens(
        db, session, token_total, breakdown=token_breakdown, emit_stop=True
    )
    # Carried on the instance (not persisted) purely so the endpoint can report
    # what this event contributed - see the hooks router, DWB-580.
    session._recorded_delta = delta

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

    ``total_tokens`` is the distinct-token (delta) sum: input + output +
    cache_creation. ``cache_read_input_tokens`` is deliberately EXCLUDED from
    the total (DWB-506) because it re-counts the same cached context on every
    turn; it is still surfaced under ``breakdown["cache_read"]``.

    Returns the same shape as parse_transcript().
    """
    total = 0
    breakdown = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    last_timestamp = None
    # DWB-539: the FIRST usage timestamp. A subagent's hook_session row is
    # created when SubagentStop fires, i.e. after the work, so stamping
    # start_time with now() and end_time with the transcript's last entry
    # produced end < start and a clamped duration of 0 for exactly the
    # token-heaviest teammates. The transcript's own span is the truth.
    first_timestamp = None

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
            # DWB-506: cache_read_input_tokens is the volume re-read from the
            # prompt cache on THIS turn - for a multi-turn session that is
            # ~the entire prior context on EVERY turn. Summing it across turns
            # is cumulative double counting: each cached token gets re-counted
            # on every subsequent turn, which inflated real sessions to
            # billions of "tokens" (session 65: 97% of a 5.47B rollup was
            # cache_read). The distinct-token (delta) measure is
            # input + output + cache_creation - the NEW tokens each turn
            # (cache_creation counts each context token exactly once, when it
            # is first written to cache). cache_read stays in the breakdown for
            # cache-efficiency visibility but is EXCLUDED from total_tokens.
            total += inp + out + cache_create
            breakdown["input"] += inp
            breakdown["output"] += out
            breakdown["cache_creation"] += cache_create
            breakdown["cache_read"] += cache_read

        ts = entry.get("timestamp")
        if ts:
            try:
                parsed_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
            else:
                # DWB-539: min/max rather than "whatever line came last", so the
                # pair is a well-defined span even if a transcript is not in
                # timestamp order. Ordered transcripts parse identically.
                if last_timestamp is None or parsed_ts > last_timestamp:
                    last_timestamp = parsed_ts
                if first_timestamp is None or parsed_ts < first_timestamp:
                    first_timestamp = parsed_ts

    return {
        "total_tokens": total,
        "breakdown": breakdown,
        "start_time": first_timestamp,
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
                "start_time": None, "end_time": None}

    try:
        projects_dir = Path(synthetic_path).parent.parent.parent
    except (ValueError, OSError):
        return {"total_tokens": 0,
                "breakdown": {"input": 0, "output": 0,
                              "cache_creation": 0, "cache_read": 0},
                "start_time": None, "end_time": None}

    if not projects_dir.exists() or not projects_dir.is_dir():
        return {"total_tokens": 0,
                "breakdown": {"input": 0, "output": 0,
                              "cache_creation": 0, "cache_read": 0},
                "start_time": None, "end_time": None}

    # Accumulate across all sibling jsonls. Most projects have just a
    # handful (one per CC session) and we want every matching line.
    aggregated_total = 0
    aggregated_breakdown = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    latest_timestamp = None
    earliest_timestamp = None  # DWB-539: real span start, see _parse_transcript_lines

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
        if parsed.get("start_time"):
            if earliest_timestamp is None or parsed["start_time"] < earliest_timestamp:
                earliest_timestamp = parsed["start_time"]

    return {
        "total_tokens": aggregated_total,
        "breakdown": aggregated_breakdown,
        "start_time": earliest_timestamp,
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

    DWB-506: total_tokens = input + output + cache_creation. cache_read is NOT
    summed into the total (it re-counts cached context every turn); it is only
    reported under breakdown["cache_read"].
    """
    transcript = Path(path)
    if not transcript.exists():
        logger.warning("Transcript not found: %s", path)
        return {
            "total_tokens": 0,
            "breakdown": {"input": 0, "output": 0,
                          "cache_creation": 0, "cache_read": 0},
            "start_time": None,
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
            "start_time": None,
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

    # DWB-580: a completed row is NO LONGER a reason to stop. It used to be:
    # `if existing and existing.status == completed: return existing`, which is
    # right for a one-shot Task subagent that stops once, and wrong for a
    # long-lived teammate resumed by SendMessage dozens of times under the SAME
    # stable subagent_id. The first stop won, the row was frozen at the first
    # turn, and every later stop was accepted, answered 200 ok, and discarded.
    # Measured at 5x under across six sessions in one day.
    #
    # What made the guard load-bearing was that re-processing DOUBLE COUNTED.
    # It no longer can: record_session_tokens diffs against the stored total,
    # so a genuinely duplicate delivery of the same event now logs a delta of
    # zero instead of a second full total. The idempotency the guard was
    # protecting is now a property of the recorder, which is the right place
    # for it, and re-processing became the feature.
    existing = db.scalar(
        select(HookSession).where(HookSession.session_id == subagent_id)
    )

    # Parse the subagent's transcript (NOT the parent's)
    agent_transcript_path = hook_data.get("agent_transcript_path")
    token_total = 0
    token_breakdown = None
    end_time = datetime.now(UTC)
    # DWB-539: the transcript's FIRST usage timestamp, when we can read it.
    # The row is created at SubagentStop (after the work), so a now()-stamped
    # start with a transcript-derived end ran backwards and every clamped
    # duration collapsed to 0. None means "no transcript span, keep the stamp".
    start_time = None

    if agent_transcript_path:
        parsed = parse_transcript(agent_transcript_path)
        token_total = parsed["total_tokens"]
        token_breakdown = parsed["breakdown"]
        if parsed.get("end_time"):
            end_time = parsed["end_time"]
        if parsed.get("start_time"):
            start_time = parsed["start_time"]

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
            if fallback.get("start_time"):
                start_time = fallback["start_time"]

    session_type = _determine_session_type(agent)

    # Resolve work context for workers
    ticket = None
    sprint_id = None
    if agent and agent.role not in OVERHEAD_ROLES:
        ticket = _resolve_ticket(db, agent, project.id)
        if ticket:
            sprint_id = ticket.sprint_id

    if existing:
        # Update the existing session.
        #
        # DWB-580: FILL-ONLY, and this only became load-bearing when the
        # completed-guard came off. This branch used to run at most once, on a
        # row that was still active. Now every later stop re-enters it, and the
        # old `x.id if x else None` assignments would CLEAR a good attribution
        # on any later stop whose resolution happened to miss - a ticket closed
        # more than five minutes ago, a marker that no longer reads. Attribution
        # that was correct would be erased by the mechanism meant to improve it,
        # and the row would look like it was never attributed at all.
        session = existing
        if agent:
            session.agent_id = agent.id
            session.session_type = session_type
            session.agent_name = agent_type
        if ticket and session.ticket_id is None:
            session.ticket_id = ticket.id
            session.sprint_id = sprint_id
            session.ticket_source = TICKET_SOURCE_RESOLVED_LATER
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
            ticket_source=TICKET_SOURCE_RESOLVED_AT_START if ticket else None,
            sprint_id=sprint_id,
            dwb_session_id=_active_dwb_session_id(db, project.id),
            status=HookSessionStatus.active,
            session_type=session_type,
            agent_name=agent_type,
        )
        db.add(session)
        db.flush()

    # Mark completed with token data.
    # DWB-539: prefer the transcript's own span so worker time_seconds reflects
    # the work, and never persist end < start (that clamped to 0 and made a
    # multi-million-token teammate read as 0 or 1 second in the rollup).
    # DWB-634: both bounds normalised to second precision HERE, at the one
    # boundary where the transcript's clock enters the row. This is the column
    # the ticket named as carrying two conventions: omitted on the three
    # constructor paths (server default, truncating) and assigned explicitly
    # here (Python, rounding). Both paths now agree.
    #
    # start AND end move together deliberately. Truncating only start would
    # leave a floored start against a rounded end and systematically inflate
    # the stored interval by up to a second, which is a new defect of the same
    # family rather than a partial fix.
    if start_time is not None:
        session.start_time = timestamps.naive_utc_second(start_time)
    end_time = timestamps.naive_utc_second(end_time)
    if session.start_time is not None and end_time < _as_naive_utc(session.start_time):
        logger.warning(
            "DWB-539: subagent %s transcript end %s precedes start %s; "
            "clamping to a zero-length interval",
            subagent_id, end_time, session.start_time,
        )
        end_time = _as_naive_utc(session.start_time)
    session.end_time = end_time
    # DWB-580: see handle_session_end. The recorder owns total_tokens and
    # token_breakdown so it can diff against what is already stored.
    session.status = HookSessionStatus.completed
    session.hook_event = "SubagentStop"

    db.commit()
    db.refresh(session)

    # Log stop + tokens through tracking.py.
    # DWB-353 routing: same as handle_session_end (see comments there).
    # DWB-580: one shared recorder for both entry points and the sweeper. It
    # owns the cumulative-vs-delta rule and the DWB-353 bucket routing.
    delta = record_session_tokens(
        db, session, token_total, breakdown=token_breakdown, emit_stop=True
    )
    # Carried on the instance (not persisted) purely so the endpoint can report
    # what this event contributed - see the hooks router, DWB-580.
    session._recorded_delta = delta

    return session


# ---------------------------------------------------------------------------
# Token recording (DWB-580)
# ---------------------------------------------------------------------------


def record_session_tokens(
    db: Session,
    session: HookSession,
    cumulative_tokens: int,
    *,
    breakdown: dict | None = None,
    emit_stop: bool,
) -> int:
    """Advance a session's recorded total and log ONLY what is new.

    Returns the delta actually logged (0 when nothing new arrived).

    THE ROW HOLDS A CUMULATIVE TOTAL, THE LOG TAKES A DELTA, and keeping those
    two straight is the whole job. A transcript is one cumulative file, so a
    re-parse always yields the running total for the whole session. But
    tracking.log_tokens and ticket.tokens_used INCREMENT. Passing the
    cumulative figure to them on every stop multiplies a ticket's tokens by its
    stop count, which is worse than recording nothing: today's numbers are at
    least wrong in one consistent direction, and a multiplied number looks
    plausible while being unbounded.

    ATOMIC AGAINST THE STORED VALUE. The previous total is read back under an
    exclusive lock on this row rather than trusted from the caller's copy, and
    the lock is held until the commit at the end. Without it, a sweep and a
    hook event landing together both read the same old total, both compute a
    delta against it, and both log: the same read-check-write race that
    DWB-567 fixed in node_exclusion.py, in the one place where a sweeper
    running unattended makes a collision likely rather than theoretical.

    A re-parse that comes back SMALLER never walks the total backwards. That
    means a truncated or rotated transcript records nothing instead of logging
    a negative delta that would silently credit tokens back.
    """
    locked = db.scalars(
        select(HookSession)
        .where(HookSession.id == session.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if locked is None:
        return 0

    previous = locked.total_tokens or 0
    cumulative = max(int(cumulative_tokens or 0), 0)
    delta = cumulative - previous

    if delta < 0:
        logger.warning(
            "DWB-580: session %s re-parsed LOWER than recorded (%s < %s); "
            "leaving the total where it is",
            locked.session_id, cumulative, previous,
        )
        delta = 0
    elif delta > 0:
        locked.total_tokens = cumulative
        if breakdown is not None:
            locked.token_breakdown = breakdown
    db.flush()

    # DWB-353 routing, single copy. Previously duplicated byte for byte at the
    # session-end and SubagentStop sites, which is how a delta rule applied in
    # one place would have survived in the other (DWB-572, same lesson).
    #   agent in OVERHEAD_ROLES (tl/pm) -> overhead bucket, even with a ticket
    #   worker with a ticket            -> ticket attribution
    #   worker without a ticket         -> ad_hoc bucket
    #   no agent at all                 -> nothing
    agent = db.get(Agent, locked.agent_id) if locked.agent_id else None
    if agent:
        if agent.role in OVERHEAD_ROLES:
            if emit_stop:
                tracking.log_overhead_stop(db, locked.project_id, agent.id)
            if delta > 0:
                # log_overhead_tokens atomically updates the per-role bucket
                # on the project row - see DWB-305 / tracking.py.
                tracking.log_overhead_tokens(
                    db, locked.project_id, agent.id, delta, source="hook"
                )
        elif locked.ticket_id:
            if emit_stop:
                tracking.log_stop(db, locked.ticket_id, agent.id)
            if delta > 0:
                tracking.log_tokens(
                    db, locked.ticket_id, agent.id, delta, source="hook"
                )
                ticket = db.get(Ticket, locked.ticket_id)
                if ticket:
                    ticket.tokens_used += delta
                    ticket.token_source = "hook"
        else:
            if emit_stop:
                tracking.log_ad_hoc_stop(db, locked.project_id, agent.id)
            if delta > 0:
                tracking.log_ad_hoc_tokens(
                    db, locked.project_id, agent.id, delta, source="hook"
                )

    db.commit()
    return delta


# Forward-only boundary for the recapture sweep (DWB-580). Captured once at
# import, which is process start. The sweep only considers rows created at or
# after this instant, so it can never reach back and "correct" a figure that
# predates the fix. Miles's ruling is that the old baseline is lost and is not
# to be chased; a sweeper that quietly repaired history would violate that
# without anybody deciding to.
_RECAPTURE_EPOCH = datetime.now(UTC).replace(tzinfo=None)


def recapture_token_growth(db: Session, *, limit: int = 200) -> tuple[int, int]:
    """Re-read transcripts that have grown since we last recorded them.

    Returns (sessions_advanced, tokens_added).

    WHY A SWEEP AND NOT JUST THE GUARD REMOVAL. Whether a resumed teammate
    emits another SubagentStop at all could not be established: an event that
    ARRIVES was proved to be discarded, the firing rate was not. Both answers
    lead here. If later stops fire, this is belt and braces; if they never
    fire, this is the only thing that captures the work. A transcript on disk
    is evidence that does not depend on a hook being delivered, so the sweep
    reads the evidence rather than waiting for the notification.

    Cheap by construction: a row is only re-parsed when its transcript file is
    larger than when we last looked, so a finished session costs one stat call
    per cycle and nothing else.
    """
    rows = db.scalars(
        select(HookSession)
        .where(HookSession.transcript_path.is_not(None))
        .where(HookSession.created_at >= _RECAPTURE_EPOCH)
        .order_by(HookSession.created_at.desc())
        .limit(limit)
    ).all()

    advanced = 0
    added = 0
    for row in rows:
        try:
            path = Path(row.transcript_path)
            if not path.is_file():
                continue
            # The recorded figure is a lower bound on the bytes it came from,
            # so a file that has not grown cannot hold anything new. One stat
            # beats one full parse.
            if path.stat().st_size <= (row.transcript_bytes or 0):
                continue
            parsed = parse_transcript(row.transcript_path)
            size = path.stat().st_size
            delta = record_session_tokens(
                db, row, parsed["total_tokens"],
                breakdown=parsed["breakdown"], emit_stop=False,
            )
            # Stamp the size we parsed AT, not the size before it, so growth
            # during the parse is picked up next cycle rather than skipped.
            row.transcript_bytes = size
            if parsed.get("end_time"):
                # DWB-634: same ingest boundary, same reason as above.
                end = timestamps.naive_utc_second(parsed["end_time"])
                if row.start_time is None or end >= _as_naive_utc(row.start_time):
                    row.end_time = end
            db.commit()
            if delta > 0:
                advanced += 1
                added += delta
        except Exception:
            # One unreadable transcript must not stop the sweep. Isolate per
            # row: a single poison entry silently costing every later row its
            # capture is the batch hazard, and this sweep runs unattended.
            db.rollback()
            logger.exception(
                "DWB-580: token recapture failed for session %s", row.session_id
            )
    if advanced:
        logger.info(
            "DWB-580: recaptured %s token(s) across %s session(s)", added, advanced
        )
    return advanced, added


def claim_unattributed_sessions(db: Session, ticket: Ticket) -> int:
    """Point a ticket's assignee's UNATTRIBUTED sessions at that ticket.

    Returns the number of sessions claimed.

    THIS INVERTS THE DIRECTION, which is the point. Resolution normally runs
    from the session side: a hook event fires and asks "what ticket is this
    agent on". That question is asked when the event happens, and on this
    project a worker is routinely spawned and briefed BEFORE its ticket is
    assigned, so the honest answer at that moment is "none" and the session
    falls to the ad_hoc bucket. Measured on 2026-09-16: sessions created
    15:07-15:15, every ticket assigned at 15:32, five of six workers
    unattributed for their whole run.

    Asking again later only helps if something asks. This side does not wait
    to be asked: the moment a ticket acquires an assignee, it tells that
    agent's still-unattributed sessions who they belong to. The answer arrives
    when it EXISTS rather than being demanded when it does not.

    FILL-ONLY and SPRINT-BOUNDED. Only rows with a NULL ticket_id are touched,
    so a session that already carries attribution is never re-pointed, and only
    rows created since the active sprint started, so this cannot reach back
    into a previous sprint's work. It does NOT move tokens that were already
    logged elsewhere: deltas recorded before the claim stay where they landed.
    That is deliberate under the forward-only ruling - this fixes where the
    NEXT delta goes, it does not rewrite the last one.
    """
    if ticket.assigned_agent_id is None:
        return 0

    stmt = (
        select(HookSession)
        .where(HookSession.project_id == ticket.project_id)
        .where(HookSession.agent_id == ticket.assigned_agent_id)
        .where(HookSession.ticket_id.is_(None))
    )

    sprint = db.get(Sprint, ticket.sprint_id) if ticket.sprint_id else None
    if sprint is not None and sprint.start_date is not None:
        window_start = datetime.combine(sprint.start_date, datetime.min.time())
        stmt = stmt.where(HookSession.created_at >= window_start)

    claimed = 0
    for row in db.scalars(stmt).all():
        row.ticket_id = ticket.id
        row.sprint_id = ticket.sprint_id
        row.ticket_source = TICKET_SOURCE_CLAIMED_BY_TICKET
        claimed += 1

    if claimed:
        db.flush()
        logger.info(
            "DWB-576: ticket %s claimed %s unattributed session(s) for agent %s",
            ticket.ticket_key, claimed, ticket.assigned_agent_id,
        )
    return claimed


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


def _active_sprint_id(db: Session, project_id: int) -> int | None:
    """The project's single active sprint, or None (DWB-539)."""
    return db.scalar(
        select(Sprint.id)
        .where(Sprint.project_id == project_id)
        .where(Sprint.status == SprintStatus.active)
        .limit(1)
    )


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """DWB-539: normalize to naive UTC for comparison against stored columns.

    Transcript timestamps and datetime.now(UTC) are tz-aware; hook_sessions
    columns are naive UTC (MySQL DATETIME). Comparing the two raises, so every
    DWB-539 interval guard normalizes first.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _resolve_ticket(db: Session, agent: Agent, project_id: int) -> Ticket | None:
    """Find the best ticket to attribute work to for a worker agent.

    Priority:
    1. In-progress ticket assigned to this agent
    2. Todo ticket assigned to this agent (most recently updated)
    3. In-review ticket assigned to this agent (most recently updated)
    4. Done ticket assigned to this agent (only if updated within last 5 minutes)
    5. None (unattributed)

    DWB-539: every lookup is scoped to the project's ACTIVE sprint when there
    is one. Without that scope the search ranged over every ticket the agent
    had ever been assigned, so a stale ticket left in_progress on a closed
    sprint outranked the work actually in hand: during S81 (sprint 160) this
    routed 6.7M tokens onto DWB-522 and 4.1M onto DWB-526, both long-done
    sprint-158 tickets, while the S81 tickets those tokens belonged to
    recorded 0. A ticket from a closed sprint is never the work in progress.
    When the project has no active sprint the old unscoped behavior stands,
    so nothing regresses for projects that do not run sprints.
    """
    sprint_id = _active_sprint_id(db, project_id)

    def _pick(status: TicketStatus, *extra_conditions) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(Ticket.project_id == project_id)
            .where(Ticket.assigned_agent_id == agent.id)
            .where(Ticket.status == status)
        )
        if sprint_id is not None:
            stmt = stmt.where(Ticket.sprint_id == sprint_id)
        for condition in extra_conditions:
            stmt = stmt.where(condition)
        return db.scalar(stmt.order_by(Ticket.updated_at.desc()).limit(1))

    # In-progress ticket assigned to this agent
    ticket = _pick(TicketStatus.in_progress)
    if ticket:
        return ticket

    # Fallback: todo ticket assigned to this agent
    ticket = _pick(TicketStatus.todo)
    if ticket:
        return ticket

    # Fallback: in_review ticket assigned to this agent
    # Workers move tickets to in_review before session ends, so SubagentStop
    # often fires after the status change.
    ticket = _pick(TicketStatus.in_review)
    if ticket:
        return ticket

    # Fallback: recently-done ticket assigned to this agent (within 5 minutes)
    # Catches cases where TL accepts a ticket quickly before SubagentStop fires.
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    return _pick(TicketStatus.done, Ticket.updated_at >= cutoff)


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


# DWB-414 / DWB-592: separating what the human typed from what the harness
# injected. Claude Code records many entries with role/type "user" that the
# human never typed: tool results, teammate-message relays, slash-command
# echoes + their stdout, task notifications, injected system reminders, and
# meta entries. Session open/close phrase detection must only fire on GENUINE
# user-authored turns, otherwise a close phrase quoted inside a tool result, a
# relayed teammate message, or an example block falsely closes the session
# (DWB-396).
#
# DWB-592 INVERTED THE MECHANISM, and the inversion is the fix. The original
# test was `startswith` over a hand-maintained tuple of wrapper tags, which
# FAILS OPEN: any wording not on the list is promoted to human input and gets
# to drive session lifecycle. That is how a relayed turn opening with the
# PROSE line "Another Claude session sent a message:" was classified as
# human-typed, and it is not a rare shape: measured over every transcript on
# this machine, the prose relay outnumbered the angle-tag relay by about ten
# to one. Adding the prose line to the tuple would have fixed that one
# instance and left the failure direction exactly where it was.
#
# The replacement is an ALLOWLIST ON PROVENANCE. Claude Code stamps a turn the
# human actually submitted with `promptSource`. Measured across 2349 user
# turns from every project on this machine, on CC 2.1.181 and 2.1.272, with
# isMeta and tool-result entries excluded:
#
#     promptSource   origin.kind         count  what it is
#     typed          human                 907  human prose
#     queued         human                  60  human prose
#     system         task-notification      53  angle-tag wrappers
#     (key absent)   (absent)             1309  990 prose relays + 319 tags
#     (key absent)   human                  20  bash / slash-command echoes
#
# Zero overlap in either direction: no typed/queued turn is wrapper-shaped and
# no wrapper-shaped turn is typed/queued. Note the last row, which is why
# `origin.kind == "human"` is NOT usable as the signal: the human did type the
# `!` or `/` that produced those echoes, so CC calls their origin human, but
# the echo turns themselves are not prose the human addressed to anyone.
#
# THIS NOW FAILS CLOSED. A wrapper wording nobody here has seen, prose or
# angle-bracket, arrives without `promptSource: typed`, so it is synthetic and
# cannot drive lifecycle. The cost is the other direction: if CC ever stops
# emitting the field, phrase detection stops firing rather than misfiring, and
# the deterministic /dwb-open and /dwb-close commands are the fallback. That
# is the right trade here - a missed open costs one command, a false close
# silently ends the tracking window for the whole project - but it is a real
# behaviour change, which is why _log_no_human_turns below makes it loud.
_HUMAN_PROMPT_SOURCES: frozenset[str] = frozenset({"typed", "queued"})

# Generic wrapper-tag shape, for the one call site that has no provenance to
# read (see _is_synthetic_user_text). Every harness wrapper observed is
# kebab-case: teammate-message, task-notification, local-command-stdout,
# user-prompt-submit-hook. Requiring at least one hyphen generalises to
# wrappers nobody has seen yet while leaving markup a human might plausibly
# type (<div>, <b>, <3) alone. Measured against the same transcripts: it
# matches all 390 angle-tag turns and none of the 967 human turns.
_WRAPPER_TAG_RE = re.compile(r"^\s*</?[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?:\s|/?>)")


def _is_human_authored_entry(entry: dict) -> bool:
    """DWB-592: True when a transcript entry is a turn the HUMAN submitted.

    Provenance allowlist, not a wrapper denylist: the entry must carry a
    `promptSource` Claude Code only stamps on a real submission. Anything else
    (a relay, an echo, a notification, a wrapper wording nobody has seen yet)
    is synthetic by default rather than by enumeration.

    The text-shape check is ANDed in as a second net, so it can only ever move
    a verdict toward synthetic, never toward human. It costs nothing and keeps
    the known wrappers caught if the provenance field is ever renamed.
    """
    if entry.get("promptSource") not in _HUMAN_PROMPT_SOURCES:
        return False
    content = (entry.get("message") or {}).get("content") or entry.get("content")
    if isinstance(content, str) and _is_synthetic_user_text(content):
        return False
    return True


def _is_synthetic_user_text(text: str) -> bool:
    """DWB-414: True when a user-role string is harness-injected rather than
    typed by the human (teammate relay, command echo/stdout, task
    notification, system reminder). Such text must not drive session
    open/close phrase detection.

    TEXT-ONLY, AND THAT IS A KNOWN LIMIT. This is the fallback for the
    UserPromptSubmit path, whose hook payload carries the prompt string and no
    provenance field, so the allowlist in _is_human_authored_entry cannot
    reach it. A generic kebab-case tag pattern beats the sixteen literals it
    replaces because it catches angle-bracket wrappers nobody has seen yet,
    but it cannot catch an unseen PROSE wrapper: prose is indistinguishable
    from prose without provenance. Closing that properly needs provenance in
    the hook payload and is a follow-up, not something to fake here by
    listing today's prose wording and calling it fixed.
    """
    return bool(_WRAPPER_TAG_RE.match(text))


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

    DWB-414 / DWB-592: only GENUINE human-authored turns are returned. Claude
    Code records tool results, teammate-message relays, slash-command echoes +
    stdout, task notifications, injected system reminders, and meta entries
    all with role/type "user". ``isMeta`` and ``toolUseResult`` entries are
    skipped outright; everything else must pass ``_is_human_authored_entry``,
    which allows a turn through only when Claude Code stamped it with a
    human ``promptSource``. That is an allowlist, so a relay wording nobody
    has seen yet is excluded by default rather than by enumeration.

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
    user_turns = 0
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

        # DWB-414: skip non-human-authored user-role entries. Meta entries and
        # tool-result echoes are never user prose; excluding them keeps quoted
        # close phrases inside tool output / injected content from firing.
        if entry.get("isMeta"):
            continue
        if "toolUseResult" in entry:
            continue

        # Counted BEFORE the provenance gate: this is the denominator that
        # makes an all-synthetic transcript distinguishable from an empty one.
        user_turns += 1

        # DWB-592: provenance allowlist. Replaces a wrapper-tag denylist that
        # failed open, promoting any unlisted wording to human input.
        if not _is_human_authored_entry(entry):
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

    # DWB-592: a transcript that HAS user turns and yields none of them is the
    # state this fix degrades into if Claude Code stops stamping provenance,
    # and it is indistinguishable from "working" at every other layer: phrase
    # detection simply stops, quietly, exactly the way 331 mis-classified
    # turns accumulated unseen. Say it out loud. Cheap because it can only
    # fire once per scan and only when the scan found nothing.
    if user_turns and not out:
        logger.warning(
            "transcript scan found %d user turn(s) but none human-authored "
            "(promptSource in %s); session phrase detection cannot fire for "
            "this transcript. If this is not a transcript of pure relays, "
            "Claude Code may have changed how it stamps prompt provenance "
            "(DWB-592). path=%s",
            user_turns,
            sorted(_HUMAN_PROMPT_SOURCES),
            path,
        )

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


# ---------------------------------------------------------------------------
# DWB-590: TOP-OFF. A periodic self-check injected mid-session.
#
# It is NOT a memory reload and it is NOT gated on `memory_mode`. Miles ruled
# top-off independent of memory mode, and spec section 8 reached the same
# conclusion: "do not gate it. It is orthogonal, about repetition and drift,
# not memory structure." The columns it reads share the `projects` table with
# the memory columns because DWB-584 held the sprint's only migration slot.
# Schema colocation is not feature coupling, and nothing below may read
# `memory_mode`. A test asserts that at the source level.
#
# Why it is programmatic rather than a playbook instruction, ruled by Miles:
# "Archies don't have to remember to turn on the top off tool! This is the
# whole point." Anything depending on an agent remembering to switch it on
# will eventually be off, and off in exactly the sessions going badly, because
# that is when an agent is least likely to run housekeeping.
# ---------------------------------------------------------------------------

# WHAT GETS INJECTED IS ONE SHORT CONSTANT LINE, RULED BY MILES: "yes... but
# its short and the same every time... not a flood of bs", with the form given
# as `••TopOff Complete <link to its page in dwb>`.
#
# THE FOUR QUESTIONS ARE NOT INJECTED. Spec section 8 lists them and an earlier
# build of this put them in the payload verbatim. Ten prompts apart, forever,
# that is the flood Miles rejected - and section 8 itself predicts why he is
# right: "Too frequent and it becomes wallpaper, and wallpaper gets skipped
# exactly like the rule it replaced."
#
# THE COST IS REAL AND IS NOT HIDDEN HERE. The marker is now the TRIGGER rather
# than the CONTENT, so the check depends on the agent knowing what the marker
# means. That makes it a rule behind a reference, which is weaker than a rule in
# front of you. The agent-facing home for the questions is the playbook; this
# module deliberately does not keep a second copy, because two homes for one
# rule is the failure the whole memory spec is about. For a reader here, the
# questions are: am I answering a question I already answered; is the user
# getting what they asked for or what I decided to give them; what am I
# asserting from a summary rather than the source; what have I been told once
# and drifted from.
#
# ONE THING IS MEASURED AND ONE IS NOT. Measured: `additionalContext` IS
# delivered on this channel. The SessionStart lane proves it - the transcript
# records it as an attachment of type `hook_additional_context` whose rendered
# form is a `<system-reminder>` block, and content over about 2KB is truncated
# to a preview plus a file on disk. NOT measured: whether Claude Code prints
# any of it in the human's terminal. That is why the injected text is kept to
# the one line Miles asked for rather than assuming he will not see it.
TOPOFF_RECEIPT = "••TopOff Complete {link}"
"""The whole human-visible payload. Short, constant, and the same every time."""

TOPOFF_LINK_PATH = "/projects/{project_id}/topoff"
"""Where the receipt points. THE PAGE DOES NOT EXIST YET and building it is a
follow-up ticket, not this one. The path follows the dashboard's existing
`/projects/:id/<thing>` shape so the view can be added under it without the
link changing. Invented pages are worse than dead links: a dead link is
obviously unfinished, where a wrong one sends the reader somewhere plausible."""

# DWB-612: how much of the firing prompt becomes the journal search term.
# Capped for two reasons, both real: a MySQL LIKE against an unbounded string
# is wasted work, and a longer literal substring only makes an exact match
# LESS likely, not more, which is the opposite of what a search is for.
_TOPOFF_SEARCH_TERM_MAX_CHARS = 300

# Prompts shorter than this are not searched. Ruled rather than left to fall
# out of the LIKE clause: a term of "ok" or "yes" would match almost any
# journal entry that happens to contain those two letters in sequence, which
# would inflate retrieval_count on entries the prompt never actually
# concerned. Below this length there is not enough prompt to be a term.
_TOPOFF_SEARCH_TERM_MIN_CHARS = 12


# The modes in which a memory transition is mid-flight, so the store is known
# to be partial. A named constant rather than an inline tuple: a mode added
# later has to be considered here, and the dangerous direction is forgetting
# one and letting the firing pass run against a half-migrated catalogue.
TRANSITION_MODES = (MemoryMode.adopting, MemoryMode.reverting)


def _topoff_search_term(prompt: str | None) -> str | None:
    """The ONE term both top-off consultations search with.

    Factored out so journal and scar matching cannot drift into searching two
    different slices of the same prompt. Miles's ruling on the scar extension
    was explicitly "same pass, same term" - a single term computed once and
    handed to both is what makes that literal, rather than two call sites that
    happen to agree today and quietly diverge later.

    Returns None when there is not enough prompt to be a term (see the
    constant above for why that floor exists); both callers treat None the
    same way, as "do not search".
    """
    if not prompt:
        return None
    stripped = prompt.strip()
    if len(stripped) < _TOPOFF_SEARCH_TERM_MIN_CHARS:
        return None
    return stripped[:_TOPOFF_SEARCH_TERM_MAX_CHARS]


def _topoff_journal_check(
    db: Session, *, agent_id: int | None, term: str | None
) -> dict:
    """DWB-612: the journal half of top-off.

    Miles's model, restated because it is the one this function exists to
    close: "during top-off, if you are repeating a mistake you search the
    journal, and that search increments the retrieval count, which is what
    eventually promotes the entry to CORE." Before this ticket top-off never
    touched the journal at all - it counted a prompt and injected one line.

    WHAT THIS DOES NOT DO: decide whether a mistake is actually being
    repeated. That is a judgment call spec section 3 and this whole audit
    keep assigning to the model, never to a script ("the model only does the
    SCAN"). What a script CAN do, and what was missing, is make the search
    HAPPEN automatically at the moment top-off fires rather than depend on an
    agent remembering to run it - the same reasoning DWB-590 already applied
    to the counter itself.

    THE TERM IS THE FIRING PROMPT, CAPPED, AND THIS IS A FIRST CUT, NOT A
    CLAIM OF GOOD RECALL. `search_entries`' `term` filter is a literal SQL
    LIKE substring match against each journal entry's body. A prompt that
    happens to share exact wording with a past journal entry will find it; a
    paraphrase will not. Better matching (tokenized, ranked, fuzzy) is
    retrieval work and belongs to its own ticket, not this wiring one. What
    this function guarantees is narrower and real: WHEN a match exists, it is
    found and counted, through the one write site journal.py already owns.

    NO SECOND INCREMENT SITE. This calls `journal_svc.search_entries`, which
    is the function Stan's audit confirmed is the only place `retrieval_count`
    is written in the application. Nothing here touches the column directly.

    `term` is computed once by `_topoff_search_term` and shared with
    `_topoff_scar_check` - this function no longer looks at the raw prompt at
    all, so the two checks cannot search different slices of it.

    Never raises: called from the fire-and-forget hook path, guarded the same
    way `_topoff_for_prompt` guards the count.
    """
    if not agent_id:
        return {"searched": False, "reason": "no_agent"}
    if not term:
        return {"searched": False, "reason": "prompt_too_short"}

    try:
        result = journal_svc.search_entries(db, agent_id=agent_id, term=term)
        db.commit()
    except journal_svc.JournalError as e:
        db.rollback()
        return {"searched": False, "reason": f"journal_error:{e.code}"}
    except Exception:
        db.rollback()
        logger.exception("_topoff_journal_check failed for agent_id=%s", agent_id)
        return {"searched": False, "reason": "error"}

    return {
        "searched": True,
        "matched": result["count"],
        "entry_ids": [e.id for e in result["entries"]],
    }


def _topoff_scar_check(db: Session, *, agent_id: int | None, term: str | None) -> dict:
    """DWB-612 extension: the scar half of top-off, ruled 2026-09-30.

    This is the resolution to the DWB-603/610/612 collision: a scar's
    `fired_count` only means something when it is reinforced by a genuine
    "have I made this error before?" consultation outside normal startup
    (Miles, verbatim). Stripping the bad firing out of `scored_memory()`
    (DWB-603/606) without replacing it would leave `fired_count` a column with
    no writer again - the exact defect the audit opened with - so Miles ruled
    top-off should BE that consultation: same trigger, same term, no agent has
    to remember to ask.

    Delegates entirely to `memory_consult.consult_scars`, which is to
    `fired_count` what `journal_svc.search_entries` is to `retrieval_count`:
    the one write site, firing only on an actual match, never on the plain
    unfiltered read `scored_memory()` still serves to injection and the
    dashboard. Nothing here touches `fired_count` directly.

    SAME TERM, SAME HONESTY ABOUT IT. `term` comes from `_topoff_search_term`,
    shared with `_topoff_journal_check` by Miles's own "same pass, same term"
    ruling. The literal-substring limitation noted on the journal side applies
    here identically, and now matters on two counters instead of one: a false
    match is a false "I have been here before" that can eventually promote a
    row to CORE, which never decays.

    Never raises: same fire-and-forget contract as its journal sibling.
    """
    if not agent_id:
        return {"searched": False, "reason": "no_agent"}
    if not term:
        return {"searched": False, "reason": "prompt_too_short"}

    try:
        result = memory_consult.consult_scars(db, agent_id=agent_id, term=term)
        db.commit()
    except memory_consult.ConsultError as e:
        db.rollback()
        return {"searched": False, "reason": f"consult_error:{e.code}"}
    except Exception:
        db.rollback()
        logger.exception("_topoff_scar_check failed for agent_id=%s", agent_id)
        return {"searched": False, "reason": "error"}

    return {
        "searched": True,
        "matched": result["count"],
        "memory_ids": [e.id for e in result["entries"]],
    }


def _topoff_for_prompt(
    db: Session, *, project: Project, session_id: str | None, prompt: str | None = None
) -> dict:
    """Count this prompt and decide whether the top-off check fires.

    RETURNS A DICT TO MERGE INTO THE CALLER'S RESPONSE. It never returns early
    on the caller's behalf and it never raises: see the contract in
    handle_user_prompt.

    DELIBERATELY DOES NOT CALL `_is_synthetic_user_text`, and that is a ruling
    rather than an oversight. Not because that filter is unreliable - it is not,
    since DWB-592 - but because it answers a different question. Top-off counts
    what HAPPENED in the session, and a relayed teammate turn is something that
    happened. See the fuller note at the call site.

    THE COUNTER IS PER CLAUDE CODE SESSION, keyed on the `session_id` the hook
    payload already carries, which makes it per agent: the unit the check is
    injected into.

    THE PROMPT-BEFORE-SessionStart CASE, which DWB-584 flagged and left to this
    ticket. A prompt can arrive before the SessionStart hook has been
    processed, so there is no `hook_sessions` row to count against. The defined
    behaviour is to skip the count and not fire, reporting `counted: false`
    with a reason.

    Creating a row here was considered and rejected: it would invent a
    hook_sessions row with no transcript, no agent and no project attribution,
    which token accounting keys on, so a housekeeping feature would be
    corrupting the cost record to avoid missing one prompt. Missing the FIRST
    prompt of a session is also the cheapest one to miss, since nothing has had
    time to drift yet.
    """
    if not project.topoff_enabled:
        # Nothing added to the response at all, so a project with top-off off
        # sees byte-identical output to before this feature existed.
        return {}

    if project.memory_mode in TRANSITION_MODES:
        # TOP-OFF IS A BACK DOOR INTO CORE WHILE A TRANSITION IS MID-FLIGHT, and
        # CORE is the tier adoption refuses to let an agent choose at all.
        #
        # The chain: the firing pass increments `fired_count` on every scar that
        # matches the term, and `memory_promote.maybe_promote_scar` sends a scar
        # to CORE at SCAR_FIRED_THRESHOLD. During `adopting` the store is being
        # populated one entry at a time, so a scar adopted early can accumulate
        # firings against a catalogue that is still most of the way in the old
        # file. It would reach CORE - which never decays - on evidence drawn
        # from a set that does not exist yet.
        #
        # `memory_decide.decide` refuses `core` outright for exactly this
        # reason: "an agent adopting its own back catalogue" is neither a human
        # ruling nor logged cross-context evidence. A concurrent top-off reaches
        # the same tier by another road, so the two guards have to agree.
        #
        # Reported rather than silent: an operator who turned top-off on and
        # sees nothing happen deserves to know it is the transition, not a
        # broken feature, and that it resumes on its own at cutover.
        return {
            "topoff": {
                "counted": False,
                "fired": False,
                "reason": "transition_in_progress",
                "memory_mode": project.memory_mode.value,
            }
        }

    if not session_id:
        return {"topoff": {"counted": False, "fired": False, "reason": "no_session_id"}}

    hook_session = db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )
    if hook_session is None:
        return {
            "topoff": {"counted": False, "fired": False, "reason": "no_hook_session"}
        }

    hook_session.prompt_count = (hook_session.prompt_count or 0) + 1
    count = hook_session.prompt_count
    db.commit()

    interval = project.topoff_interval
    if not interval or interval < 1:
        # The column is a plain int and an operator can set it to 0. Modulo by
        # zero would raise inside a fire-and-forget hook, so this is guarded
        # rather than trusted, and it is reported rather than silently treated
        # as "off".
        return {
            "topoff": {
                "counted": True,
                "fired": False,
                "prompt_count": count,
                "reason": "invalid_interval",
            }
        }

    if count % interval != 0:
        return {
            "topoff": {
                "counted": True,
                "fired": False,
                "prompt_count": count,
                "interval": interval,
            }
        }

    # DWB-612: both consultations, run only when the check actually FIRES -
    # same cadence as the receipt, not every prompt. A search on every prompt
    # would be a different, heavier feature (and would inflate the counts on
    # whatever the prompt of the moment happened to contain); this runs at
    # exactly the moment the agent is told to self-check.
    #
    # ONE TERM, COMPUTED ONCE, HANDED TO BOTH. Miles's ruling on the scar
    # extension was explicitly "same pass, same term" - computing it twice
    # (once per check) would let the two searches drift onto different
    # slices of the prompt the moment either call site changed independently.
    term = _topoff_search_term(prompt)
    journal_check = _topoff_journal_check(db, agent_id=hook_session.agent_id, term=term)
    scar_check = _topoff_scar_check(db, agent_id=hook_session.agent_id, term=term)

    return {
        "topoff": {
            "counted": True,
            "fired": True,
            "prompt_count": count,
            "interval": interval,
            "journal_check": journal_check,
            "scar_check": scar_check,
        },
        # The return channel Claude Code reads from the hook's stdout, the same
        # one DWB-517 uses on SessionStart. `hookEventName` must match the hook
        # that is firing.
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": TOPOFF_RECEIPT.format(
                link=settings.DASHBOARD_BASE_URL
                + TOPOFF_LINK_PATH.format(project_id=project.id)
            ),
        },
    }


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
    # DWB-590: bound before the try so the exception path below can merge it
    # too. If top-off has already fired and counted, a later failure in the
    # phrase ladders must not swallow the injected check: the prompt has been
    # counted either way, so dropping the block here would skip that interval
    # entirely rather than retry it.
    extra: dict = {}
    try:
        prompt = hook_data.get("prompt")
        if not prompt:
            return {"status": "noop", "reason": "no_prompt"}

        # DWB-590: project resolution moved ABOVE the synthetic check, because
        # top-off needs the project row for topoff_enabled / topoff_interval
        # and must run for synthetic turns too. Safe to move: _resolve_project
        # is two SELECTs and nothing else, so the earlier position was an
        # optimisation, never a correctness property.
        cwd = hook_data.get("cwd", "")
        project = _resolve_project(db, cwd)
        if not project:
            return {"status": "noop", "reason": "no_project_for_cwd"}

        # DWB-590: count this prompt and decide whether the top-off check
        # fires. `extra` is MERGED into every return below and this branch
        # NEVER returns on its own.
        #
        # THAT IS A HARD REQUIREMENT, NOT A STYLE CHOICE. A prompt can be both
        # the Nth AND a close phrase. If top-off returned early, that prompt
        # would silently fail to close the session: a housekeeping feature
        # eating a session boundary, which is strictly worse than the drift it
        # exists to catch, and invisible for weeks because the top-off output
        # would look perfectly correct while the session record lost its end.
        extra.update(
            _topoff_for_prompt(
                db,
                project=project,
                session_id=hook_data.get("session_id"),
                prompt=prompt,
            )
        )

        # DWB-414: scope phrase detection to genuine user-authored turns. If
        # the submitted prompt is itself harness-injected synthetic content
        # (a relayed teammate message, a slash-command echo, a re-injected
        # hook block), it is not the human commanding a close/open and must
        # not trip the regex ladders. Matched in-memory; nothing persisted.
        #
        # DWB-590: TOP-OFF DELIBERATELY DOES NOT USE THIS FILTER, and the
        # reason is NOT that the filter is unreliable.
        #
        # An earlier version of this comment said "do not couple them, this
        # filter is missing the dominant relay shape". That argument expires:
        # DWB-592 fixed the filter, so a reason resting on its weakness invites
        # coupling the moment it becomes trustworthy. Reworded on Freddie's
        # point, which is the better one.
        #
        # The durable reason: TOP-OFF COUNTS WHAT HAPPENED IN THE SESSION, and
        # a relayed teammate turn is something that happened. The count is a
        # measure of elapsed work, not a judgement about who authored a turn.
        # This filter answers a different question - "is the human commanding a
        # close or open" - where a false positive destroys tracking data. Two
        # questions, two answers, and the fact that one of them is now
        # well-implemented does not make it the answer to the other.
        #
        # Two tests assert both relay shapes still count.
        if _is_synthetic_user_text(prompt):
            return {"status": "noop", "reason": "synthetic_prompt", **extra}

        # ---- Open path (DWB-344) ----
        open_phrase = match_open(prompt)
        if open_phrase:
            # Single-active guard: defer to open_session for the actual
            # race-safe check, but short-circuit here so the common case
            # doesn't churn the transaction.
            if dwb_svc.get_active_session(db, project.id) is not None:
                return {"status": "noop", "reason": "already_open", **extra}

            new_session, _existing = dwb_svc.open_session(
                db,
                project_id=project.id,
                opened_at=datetime.now(UTC),
                open_method=DwbOpenMethod.regex,
                open_phrase=open_phrase,
            )
            if new_session is None:
                # Lost the race; another caller opened concurrently.
                return {"status": "noop", "reason": "already_open", **extra}
            db.commit()
            return {
                "status": "opened",
                "dwb_session_id": new_session.id,
                "open_phrase": open_phrase,
                **extra,
            }

        # ---- Close path (DWB-377) ----
        close_phrase = match_close(prompt)
        if close_phrase:
            active = dwb_svc.get_active_session(db, project.id)
            if active is None:
                return {"status": "noop", "reason": "no_active_session", **extra}
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
                **extra,
            }

        # ---- Neither ladder matched ----
        # DWB-402: the Layer-2 Haiku AI classifier fallback (DWB-382) was
        # retired. A non-matching prompt is simply a noop; the deterministic
        # slash commands, regex layer, and idle sweeper cover the rest.
        return {"status": "noop", "reason": "no_phrase_match", **extra}
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
        return {"status": "error", "detail": f"{type(e).__name__}: {e}", **extra}


# ---------------------------------------------------------------------------
# DWB-417..421: agent tool-action + lifecycle capture (agent scoring).
#
# Claude Code fires PostToolUse after every tool call and lifecycle hooks
# (Notification, PreCompact) at other moments. We persist one tool_actions row
# per event, resolving agent / dwb_session / ticket context from the hook
# session_id the SAME way handle_session_end resolves attribution: first an
# existing hook_session row keyed on session_id (which already carries the
# resolved agent/ticket/dwb_session), then the authoritative marker
# (resolve_agent_from_marker), then _resolve_ticket / _active_dwb_session_id to
# fill the gaps. Every FK is nullable: an unresolvable session_id still persists
# a row with null context rather than erroring (delivery-gap tolerance - the
# hooks are fire-and-forget via curl -sf).
#
# DWB-417 laid the foundation (generic event_type='tool_use'). DWB-418..421 add
# per-tool classification on top of the same row shape + resolution path:
#   Write/Edit/MultiEdit/NotebookEdit -> file_written   (target=file path)
#   SendMessage                       -> message_sent    (target=recipient)
#   Task                              -> agent_spawned   (target=child identity)
#   Notification (lifecycle)          -> notification    (target=message)
#   PreCompact (lifecycle)            -> context_compaction (target=trigger)
#   anything else                     -> tool_use        (generic fallback)
# Each classified (non-fallback) event also emits a matching semantic verb into
# the activity feed via log_activity (entity_type="tool_action"). The generic
# 'tool_use' fallback does NOT emit a feed verb - it would flood the feed with
# every Read/Bash/Grep. The inbound message BODY of a SendMessage is never
# persisted (no-user-text-in-DB rule); only the recipient + optional short
# agent-authored subject are kept.
# ---------------------------------------------------------------------------

# Tools whose invocation means "an agent wrote a file".
_FILE_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

# event_type values that warrant a semantic activity-feed verb. The generic
# 'tool_use' fallback is intentionally excluded (feed-noise control).
_FEED_VERB_EVENTS = frozenset({
    "file_written",
    "message_sent",
    "agent_spawned",
    "notification",
    "context_compaction",
})

# Max chars persisted to the target column (matches the VARCHAR(1024) width)
# and to short JSON metadata fields.
_TARGET_MAX = 1024
_META_TEXT_MAX = 200


def _truncate(value, length: int) -> str | None:
    """Coerce to str and cap length; None passes through as None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value[:length]


def _classify_tool_action(
    tool_name: str, tool_input: dict | None
) -> tuple[str, str | None, dict | None]:
    """Map a PostToolUse (tool_name, tool_input) to (event_type, target,
    metadata) per DWB-418..420.

    Returns the generic ('tool_use', None, None) for any tool that isn't one of
    the classified verbs, so unmatched tools still persist a row (DWB-417
    foundation contract) without emitting a feed verb.
    """
    ti = tool_input if isinstance(tool_input, dict) else {}

    # DWB-418: file writes.
    if tool_name in _FILE_WRITE_TOOLS:
        target = ti.get("file_path") or ti.get("notebook_path")
        return "file_written", _truncate(target, _TARGET_MAX), None

    # DWB-419: agent-to-agent messages. Persist recipient + optional short
    # subject; NEVER the message body (no-user-text-in-DB rule).
    if tool_name == "SendMessage":
        target = ti.get("to")
        metadata = None
        subject = ti.get("summary")
        if isinstance(subject, str) and subject.strip():
            metadata = {"subject": _truncate(subject.strip(), _META_TEXT_MAX)}
        return "message_sent", _truncate(target, _TARGET_MAX), metadata

    # DWB-420: spawns. Target is the most identifying child handle; keep the
    # description (when distinct) in metadata for context.
    if tool_name == "Task":
        target = ti.get("subagent_type") or ti.get("name") or ti.get("description")
        metadata = None
        desc = ti.get("description")
        if isinstance(desc, str) and desc.strip():
            metadata = {"description": _truncate(desc.strip(), _META_TEXT_MAX)}
        return "agent_spawned", _truncate(target, _TARGET_MAX), metadata

    # Generic fallback (DWB-417): unmatched tool, no feed verb.
    return "tool_use", None, None


def _resolve_tool_action_context(
    db: Session,
    *,
    session_id: str | None,
    cwd: str,
    hook_event: str,
    hook_data: dict,
) -> tuple[Project | None, int | None, int | None, int | None]:
    """Resolve (project, agent_id, ticket_id, dwb_session_id) for a tool_actions
    row from a hook session_id, mirroring handle_session_end's order:

      1. Resolve project from cwd.
      2. Existing hook_session for session_id -> inherit agent/ticket/dwb_session.
      3. No agent yet + project known -> authoritative marker resolve, then
         _resolve_ticket for a worker.
      4. dwb_session_id still null + project known -> _active_dwb_session_id.

    Any unresolved piece stays None (delivery-gap tolerance). Shared by both
    handle_tool_use (PostToolUse) and handle_lifecycle_event (Notification /
    PreCompact).
    """
    agent_id: int | None = None
    ticket_id: int | None = None
    dwb_session_id: int | None = None

    project = _resolve_project(db, cwd) if cwd else None

    if session_id:
        existing = db.scalar(
            select(HookSession).where(HookSession.session_id == session_id)
        )
        if existing is not None:
            agent_id = existing.agent_id
            ticket_id = existing.ticket_id
            dwb_session_id = existing.dwb_session_id
            if project is None and existing.project_id:
                project = db.get(Project, existing.project_id)

    if agent_id is None and project is not None and session_id:
        agent = resolve_agent_from_marker(
            db, project, session_id,
            hook_event=hook_event,
            hook_data=hook_data,
        )
        if agent is not None:
            agent_id = agent.id
            if agent.role not in OVERHEAD_ROLES:
                ticket = _resolve_ticket(db, agent, project.id)
                if ticket is not None:
                    ticket_id = ticket.id

    if dwb_session_id is None and project is not None:
        dwb_session_id = _active_dwb_session_id(db, project.id)

    return project, agent_id, ticket_id, dwb_session_id


def _persist_tool_action(
    db: Session,
    *,
    project: Project | None,
    agent_id: int | None,
    ticket_id: int | None,
    dwb_session_id: int | None,
    session_id: str | None,
    tool_name: str,
    event_type: str,
    target: str | None,
    metadata: dict | None,
) -> ToolAction:
    """Persist one tool_actions row and, for classified (non-fallback) events,
    emit a matching semantic activity-feed verb.

    The row is committed first so it survives even if the (best-effort) feed
    emission fails. The feed emission is wrapped so a feed failure never breaks
    the hook's 200-always contract and never loses the captured row.
    """
    action = ToolAction(
        agent_id=agent_id,
        session_id=session_id,
        dwb_session_id=dwb_session_id,
        ticket_id=ticket_id,
        tool_name=tool_name,
        target=target,
        event_type=event_type,
        tool_metadata=metadata,
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    # Semantic feed verb (DWB-418..421). Only for classified events, and only
    # when a project resolved (activity_log.project_id is NOT NULL).
    if event_type in _FEED_VERB_EVENTS and project is not None:
        try:
            feed_details: dict = {"tool_name": tool_name, "target": target}
            if metadata:
                feed_details.update(metadata)
            log_activity(
                db,
                project.id,
                agent_id,
                "tool_action",
                action.id,
                event_type,
                feed_details,
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception(
                "tool_action feed verb failed (event_type=%s, id=%s)",
                event_type, action.id,
            )
            log_failed_hook(
                hook_event=event_type,
                status_code=None,
                raw_payload={"tool_action_id": action.id, "event_type": event_type},
                error=f"{type(e).__name__}: {e}",
            )

    return action


def handle_tool_use(db: Session, hook_data: dict) -> ToolAction:
    """Persist one tool_actions row for a PostToolUse hook event (DWB-417..420).

    Classifies the tool into a semantic event_type + target (file path,
    recipient, child agent), persists the row, and emits a matching activity-
    feed verb for classified events. Unmatched tools fall back to the generic
    'tool_use' event with no feed verb.

    Never raises for an unknown/missing session_id; the caller (router)
    additionally swallows + 200s on error.
    """
    session_id = (hook_data.get("session_id") or "").strip() or None
    tool_name = (hook_data.get("tool_name") or "").strip()
    tool_input = hook_data.get("tool_input")
    cwd = hook_data.get("cwd", "")
    hook_event = hook_data.get("hook_event_name") or "PostToolUse"

    project, agent_id, ticket_id, dwb_session_id = _resolve_tool_action_context(
        db, session_id=session_id, cwd=cwd, hook_event=hook_event, hook_data=hook_data,
    )

    event_type, target, metadata = _classify_tool_action(tool_name, tool_input)

    return _persist_tool_action(
        db,
        project=project,
        agent_id=agent_id,
        ticket_id=ticket_id,
        dwb_session_id=dwb_session_id,
        session_id=session_id,
        tool_name=tool_name,
        event_type=event_type,
        target=target,
        metadata=metadata,
    )


def handle_lifecycle_event(db: Session, hook_data: dict) -> ToolAction:
    """Persist one tool_actions row for a Notification or PreCompact lifecycle
    hook (DWB-421). These are NOT tool calls, so they reuse the tool_actions
    table with a lifecycle event_type:

      Notification -> event_type='notification',       target=the message
      PreCompact   -> event_type='context_compaction', target=the trigger

    tool_name is set to the hook event name (Notification / PreCompact) so the
    row is self-describing. Context resolution + the 200-always, never-raise
    contract match handle_tool_use. An unrecognized hook_event_name falls back
    to the generic 'tool_use' event (no feed verb) rather than erroring.
    """
    session_id = (hook_data.get("session_id") or "").strip() or None
    cwd = hook_data.get("cwd", "")
    hook_event = (hook_data.get("hook_event_name") or "").strip()

    if hook_event == "Notification":
        event_type = "notification"
        target = _truncate(hook_data.get("message"), _TARGET_MAX)
        tool_name = "Notification"
    elif hook_event == "PreCompact":
        event_type = "context_compaction"
        target = _truncate(hook_data.get("trigger"), _TARGET_MAX)
        tool_name = "PreCompact"
    else:
        # Unknown lifecycle event - persist a generic row, no feed verb.
        event_type = "tool_use"
        target = None
        tool_name = hook_event or "lifecycle"

    project, agent_id, ticket_id, dwb_session_id = _resolve_tool_action_context(
        db, session_id=session_id, cwd=cwd,
        hook_event=hook_event or "lifecycle", hook_data=hook_data,
    )

    return _persist_tool_action(
        db,
        project=project,
        agent_id=agent_id,
        ticket_id=ticket_id,
        dwb_session_id=dwb_session_id,
        session_id=session_id,
        tool_name=tool_name,
        event_type=event_type,
        target=target,
        metadata=None,
    )


# DWB-447: varchar caps for the inter_agent_messages row (table is varchar(255)
# for the agent names, varchar(512) for the summary; body is TEXT/uncapped).
_AGENT_NAME_MAX = 255
_SUMMARY_MAX = 512


def handle_agent_message(db: Session, hook_data: dict) -> InterAgentMessage | None:
    """Capture one agent-to-agent SendMessage into inter_agent_messages (DWB-447).

    The SENDER is resolved from the Claude Code ``session_id`` via the SAME
    resolver token attribution + tool-action capture use
    (``_resolve_tool_action_context``); for an established session the agent
    comes from the existing hook_session, so no marker is consumed. The
    RECIPIENT is resolved best-effort by name within the sender's project
    (``resolve_agent``) - ``to_agent_name`` is ALWAYS stored even when the FK
    can't resolve.

    Returns the persisted row, or ``None`` (nothing stored) when:
      - the project can't be resolved (project_id is NOT NULL), or
      - ``project.capture_agent_comms`` is false (capture disabled).

    Agent message bodies are NOT user text - they ARE stored (unlike Layer-2
    open/close phrases). ``dwb_session_id`` is stamped for display only when a
    session is open; it is never used to purge.
    """
    session_id = (hook_data.get("session_id") or "").strip() or None
    cwd = hook_data.get("cwd", "") or ""
    to_name = _truncate((hook_data.get("to") or "").strip() or None, _AGENT_NAME_MAX)
    body = hook_data.get("message") or ""
    summary = _truncate(hook_data.get("summary"), _SUMMARY_MAX)

    project, from_agent_id, _ticket_id, dwb_session_id = _resolve_tool_action_context(
        db, session_id=session_id, cwd=cwd,
        hook_event="SendMessage", hook_data=hook_data,
    )

    # project_id is NOT NULL: with no project we cannot store. Per contract this
    # is a captured:false 200, not an error.
    if project is None:
        return None
    # Per-project capture gate (DWB-446 flag, default TRUE).
    if not project.capture_agent_comms:
        return None

    from_agent_name = None
    if from_agent_id is not None:
        sender = db.get(Agent, from_agent_id)
        from_agent_name = _truncate(sender.name, _AGENT_NAME_MAX) if sender else None

    to_agent = resolve_agent(db, to_name, project.id) if to_name else None
    to_agent_id = to_agent.id if to_agent is not None else None

    msg = InterAgentMessage(
        project_id=project.id,
        dwb_session_id=dwb_session_id,
        from_agent_id=from_agent_id,
        from_agent_name=from_agent_name,
        to_agent_name=to_name,
        to_agent_id=to_agent_id,
        body=body,
        summary=summary,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


# DWB-443: chars of each message body echoed into a Stop-hook channel poke.
_POKE_BODY_MAX = 100


def handle_channel_poke(db: Session, hook_data: dict) -> dict:
    """Stop-hook Archie-channel poke (DWB-443).

    Resolves the stopping agent from the hook payload (same marker/session
    resolution as the tool-use + session-end hooks). If that agent is a
    team-lead with UNREAD channel messages, returns a Stop ``block`` decision
    listing them and marks them read (the same surfaced-read path DWB-438 uses
    for identity.md), so an archie is nudged to read the channel before the
    session ends and never sees the same message twice.

    Returns ``{}`` (no block) when the agent can't be resolved, is not a
    team-lead, or has nothing unread. NEVER raises - any exception yields ``{}``
    so the Stop hook can never break or stall the session.
    """
    try:
        session_id = (hook_data.get("session_id") or "").strip() or None
        cwd = hook_data.get("cwd", "") or ""
        hook_event = (
            hook_data.get("hook_event_name") or hook_data.get("hook_event") or "Stop"
        )
        _project, agent_id, _ticket_id, _dwb = _resolve_tool_action_context(
            db, session_id=session_id, cwd=cwd, hook_event=hook_event, hook_data=hook_data,
        )
        if agent_id is None:
            return {}

        from app.services import tl_channel as tl_channel_svc  # local: avoid cycle

        agent = db.get(Agent, agent_id)
        # Channel is team-lead-only (matches DWB-438 identity surfacing); a
        # non-TL never gets poked even though broadcasts are technically visible.
        if agent is None or not tl_channel_svc.is_team_lead(agent):
            return {}

        unread = tl_channel_svc.unread_for_agent(db, agent_id)
        if not unread:
            return {}

        parts = []
        for m in unread:
            kind = "broadcast" if m.get("is_broadcast") else "direct"
            sender = m.get("from_agent_name") or f"agent {m.get('from_agent_id')}"
            prefix = m.get("from_project_prefix")
            who = f"{sender}({prefix})" if prefix else sender
            body = (m.get("body") or "").strip().replace("\n", " ")
            if len(body) > _POKE_BODY_MAX:
                body = body[:_POKE_BODY_MAX].rstrip() + "..."
            parts.append(f"[{kind}] from {who}: {body}")
        n = len(unread)
        reason = (
            f"You have {n} Archie Channel message{'s' if n != 1 else ''}: "
            + " ; ".join(parts)
            + ". Reply via /tl or POST /api/tl-channel."
        )

        # Mark the surfaced messages read (same path DWB-438 uses), then commit.
        for m in unread:
            tl_channel_svc.mark_read(db, agent_id=agent_id, message_id=m["id"])
        db.commit()

        return {"decision": "block", "reason": reason}
    except Exception:
        db.rollback()
        logger.warning("channel-poke failed; returning no-block", exc_info=True)
        return {}


# DWB-353: _create_unattributed_alert was deleted along with its two call
# sites in handle_session_end and handle_subagent_stop. The "unattributed"
# alert class is gone - worker-without-ticket tokens now flow into the
# ad_hoc bucket (see DWB-353 in tracking.py); no-agent-at-all sessions
# silently drop their tokens (rare; not worth paging on).
