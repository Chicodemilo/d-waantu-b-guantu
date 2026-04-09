# Path: app/routers/hooks.py
# File: hooks.py
# Created: 2026-04-09
# Purpose: HTTP endpoints for Claude Code lifecycle hooks (SessionStart, SessionEnd, SubagentStop)
# Caller: app/main.py
# Callees: app/services/hook_tracking.py
# Data In: HTTP POST from curl hook commands
# Data Out: JSON responses (HookSession data)
# Last Modified: 2026-04-09

"""Hook endpoints for passive tracking.

CRITICAL: These endpoints must NEVER return 5xx. Claude Code hooks are
fire-and-forget — errors are logged as alerts but always return 200.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hook_session import HookSessionStatus
from app.schemas.hook_session import HookEventInput, HookSessionRead
from app.services import hook_tracking as svc

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
        return {
            "status": "error",
            "detail": str(e),
        }


@router.get("/sessions", response_model=list[HookSessionRead])
def list_hook_sessions(
    project_id: int | None = Query(None),
    status: HookSessionStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    """List hook sessions with optional filters."""
    return svc.list_sessions(db, project_id=project_id, status=status)


@router.get("/sessions/{session_id}", response_model=HookSessionRead)
def get_hook_session(session_id: str, db: Session = Depends(get_db)):
    """Get a single hook session by its Claude Code session_id."""
    session = svc.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Hook session not found")
    return session
