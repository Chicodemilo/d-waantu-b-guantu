# Path: app/routers/hooks.py
# File: hooks.py
# Created: 2026-04-09
# Purpose: HTTP endpoints for Claude Code lifecycle hooks (SessionStart, SessionEnd, SubagentStop, UserPromptSubmit)
# Caller: app/main.py
# Callees: app/services/hook_tracking.py, app/services/failed_hook.py, app/models/hook_session.py
# Data In: HTTP POST from curl hook commands
# Data Out: JSON responses (HookSession data)
# Last Modified: 2026-06-09

"""Hook endpoints for passive tracking.

CRITICAL: These endpoints must NEVER return 5xx. Claude Code hooks are
fire-and-forget — errors are logged as alerts but always return 200.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hook_session import HookSessionStatus
from app.schemas.hook_session import (
    HookEventInput,
    HookSessionRead,
)
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
def hook_user_prompt(data: HookEventInput, db: Session = Depends(get_db)):
    """Receive a UserPromptSubmit hook event from Claude Code (DWB-344).

    Fast-path open-phrase detection: CC fires this hook the instant the user
    submits a message and includes the raw prompt text in the payload, so we
    can open the DWB session synchronously without waiting for the next
    SessionEnd retry.

    Like the other hook endpoints, this MUST NEVER return 5xx. Every failure
    swallows, logs to failed_hooks, and returns HTTP 200.
    """
    try:
        result = svc.handle_user_prompt(db, data.model_dump())
        return result
    except Exception as e:
        # Belt-and-suspenders: the service already swallows, but if anything
        # leaks (e.g. pydantic edge case before the service is entered)
        # we still 200 the caller.
        logger.exception("hook_user_prompt error")
        log_failed_hook(
            hook_event=data.hook_event_name or "UserPromptSubmit",
            status_code=200,
            raw_payload=data.model_dump(),
            error=f"{type(e).__name__}: {e}",
        )
        return {
            "status": "error",
            "detail": str(e),
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
