# Path: app/routers/hooks.py
# File: hooks.py
# Created: 2026-04-09
# Purpose: HTTP endpoints for Claude Code lifecycle hooks (SessionStart, SessionEnd, SubagentStop, UserPromptSubmit) + git post-commit hook auto-close (DWB-345); DWB-402 retired the UserPromptSubmit Layer-2 Haiku classifier
# Caller: app/main.py
# Callees: app/services/hook_tracking.py, app/services/failed_hook.py, app/services/git_hook.py, app/models/hook_session.py
# Data In: HTTP POST from curl hook commands
# Data Out: JSON responses (HookSession data, post-commit close result)
# Last Modified: 2026-06-11

"""Hook endpoints for passive tracking.

CRITICAL: These endpoints must NEVER return 5xx. Claude Code hooks are
fire-and-forget — errors are logged as alerts but always return 200.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hook_session import HookSessionStatus
from app.schemas.git_hook import PostCommitRequest, PostCommitResponse
from app.schemas.hook_session import (
    HookEventInput,
    HookSessionRead,
)
from app.services import git_hook as git_hook_svc
from app.services import hook_tracking as svc
from app.services.failed_hook import log_failed_hook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


@router.post("/session-start", status_code=200)
def hook_session_start(data: HookEventInput, db: Session = Depends(get_db)):
    """Receive a SessionStart hook event from Claude Code."""
    try:
        session = svc.handle_session_start(db, data.model_dump())
        return {
            "status": "ok",
            "session_id": session.session_id,
            "hook_session_id": session.id,
        }
    except Exception as e:
        logger.exception("hook_session_start error")
        log_failed_hook(
            hook_event=data.hook_event_name or "SessionStart",
            status_code=200,
            raw_payload=data.model_dump(),
            error=f"{type(e).__name__}: {e}",
        )
        return {
            "status": "error",
            "detail": str(e),
        }


@router.post("/session-end", status_code=200)
def hook_session_end(data: HookEventInput, db: Session = Depends(get_db)):
    """Receive a SessionEnd or SubagentStop hook event from Claude Code."""
    try:
        session = svc.handle_session_end(db, data.model_dump())
        return {
            "status": "ok",
            "session_id": session.session_id,
            "hook_session_id": session.id,
            "total_tokens": session.total_tokens,
        }
    except Exception as e:
        logger.exception("hook_session_end error")
        log_failed_hook(
            hook_event=data.hook_event_name or "SessionEnd",
            status_code=200,
            raw_payload=data.model_dump(),
            error=f"{type(e).__name__}: {e}",
        )
        return {
            "status": "error",
            "detail": str(e),
        }


@router.post("/user-prompt", status_code=200)
def hook_user_prompt(
    data: HookEventInput,
    db: Session = Depends(get_db),
):
    """Receive a UserPromptSubmit hook event from Claude Code (DWB-344,
    DWB-377).

    Fast-path open-phrase detection: CC fires this hook the instant the user
    submits a message and includes the raw prompt text in the payload, so we
    can open the DWB session synchronously without waiting for the next
    SessionEnd retry.

    DWB-402: the Layer-2 Haiku AI classifier backstop (DWB-382) was retired. A
    prompt that matches neither the open nor close regex is a plain noop;
    deterministic /dwb-open + /dwb-close slash commands, the regex layer, and
    the idle sweeper cover lifecycle from here.

    Like the other hook endpoints, this MUST NEVER return 5xx. Every failure
    swallows, logs to failed_hooks, and returns HTTP 200.

    DWB-351 privacy: the inbound ``prompt`` is matched in-memory by the
    service and never persisted. The exception-path log_failed_hook call below
    scrubs ``prompt`` from the payload before writing the failed_hooks row,
    mirroring the service-layer scrub.
    """
    try:
        result = svc.handle_user_prompt(db, data.model_dump())
        return result
    except Exception as e:
        # Belt-and-suspenders: the service already swallows, but if anything
        # leaks (e.g. pydantic edge case before the service is entered)
        # we still 200 the caller.
        # DWB-351: scrub the user-typed prompt from the raw payload.
        payload = data.model_dump()
        if "prompt" in payload and payload["prompt"] is not None:
            payload["prompt"] = "<redacted>"
        logger.exception("hook_user_prompt error")
        log_failed_hook(
            hook_event=data.hook_event_name or "UserPromptSubmit",
            status_code=200,
            raw_payload=payload,
            error=f"{type(e).__name__}: {e}",
        )
        return {
            "status": "error",
            "detail": str(e),
        }


@router.post("/post-commit", response_model=PostCommitResponse, status_code=200)
def hook_post_commit(data: PostCommitRequest, db: Session = Depends(get_db)):
    """Parse commit message for <PREFIX>-NNN tokens and auto-close any
    in_progress / in_review tickets to done (DWB-345).

    Same fire-and-forget contract as the other hook endpoints: any error
    is logged and returned as a 200 so the shell hook never blocks a
    commit. Silently no-ops when repo_path doesn't match a known project
    (a hook firing from a clone of an unrelated repo is normal).
    """
    try:
        result = git_hook_svc.process_post_commit(
            db,
            repo_path=data.repo_path,
            commit_message=data.commit_message,
            commit_sha=data.commit_sha,
        )
        return result
    except Exception as e:
        logger.exception("hook_post_commit error")
        log_failed_hook(
            hook_event="PostCommit",
            status_code=200,
            raw_payload=data.model_dump(),
            error=f"{type(e).__name__}: {e}",
        )
        # Still 200 with the failure shape - the hook treats anything
        # non-2xx as a block-the-commit signal.
        return {
            "project_id": None,
            "project_prefix": None,
            "commit_sha": data.commit_sha,
            "closed": [],
            "skipped": [],
            "unknown": [],
            "reason": f"error: {type(e).__name__}",
        }


@router.get("/sessions", response_model=list[HookSessionRead])
def list_hook_sessions(
    project_id: int | None = Query(None),
    status: str | None = Query(None, description="active|completed|error|orphan"),
    cutoff_minutes: int = Query(30, ge=1, le=10080, description="Used only when status=orphan"),
    db: Session = Depends(get_db),
):
    """List hook sessions with optional filters.

    `status=orphan` is a synthetic value: returns active sessions whose
    `start_time` is older than `cutoff_minutes` (default 30). The
    `elapsed_seconds` field on each row is populated only for orphan rows.
    """
    if status == "orphan":
        paired = svc.list_orphan_sessions(
            db, project_id=project_id, cutoff_minutes=cutoff_minutes
        )
        out: list[HookSessionRead] = []
        for session, elapsed in paired:
            row = HookSessionRead.model_validate(session)
            row.elapsed_seconds = elapsed
            out.append(row)
        return out

    real_status: HookSessionStatus | None = None
    if status is not None:
        try:
            real_status = HookSessionStatus(status)
        except ValueError:
            raise HTTPException(
                400, f"invalid status '{status}'; expected one of active|completed|error|orphan"
            )
    return svc.list_sessions(db, project_id=project_id, status=real_status)


@router.get("/sessions/{session_id}", response_model=HookSessionRead)
def get_hook_session(session_id: str, db: Session = Depends(get_db)):
    """Get a single hook session by its Claude Code session_id."""
    session = svc.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Hook session not found")
    return session
