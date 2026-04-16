# Path: app/routers/hooks.py
# File: hooks.py
# Created: 2026-04-09
# Purpose: HTTP endpoints for Claude Code lifecycle hooks and teammate session registration
# Caller: app/main.py
# Callees: app/services/hook_tracking.py, app/models/hook_session.py
# Data In: HTTP POST from curl hook commands and teammate registration requests
# Data Out: JSON responses (HookSession data)
# Last Modified: 2026-04-16

"""Hook endpoints for passive tracking.

CRITICAL: These endpoints must NEVER return 5xx. Claude Code hooks are
fire-and-forget — errors are logged as alerts but always return 200.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.schemas.hook_session import (
    DeregisterAgentInput,
    HookEventInput,
    HookSessionRead,
    RegisterAgentInput,
)
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


@router.post("/register-agent", status_code=200)
def register_agent(data: RegisterAgentInput, db: Session = Depends(get_db)):
    """Register a teammate as an active hook session (idempotent)."""
    try:
        existing = db.scalars(
            select(HookSession)
            .where(HookSession.project_id == data.project_id)
            .where(HookSession.agent_id == data.agent_id)
            .where(HookSession.status == HookSessionStatus.active)
            .limit(1)
        ).first()
        if existing:
            return {
                "status": "ok",
                "session_id": existing.session_id,
                "hook_session_id": existing.id,
                "already_active": True,
            }

        session = HookSession(
            session_id=str(uuid.uuid4()),
            agent_id=data.agent_id,
            project_id=data.project_id,
            agent_name=data.agent_name,
            session_type=HookSessionType.teammate,
            status=HookSessionStatus.active,
            start_time=datetime.now(timezone.utc),
            hook_event="register-agent",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return {
            "status": "ok",
            "session_id": session.session_id,
            "hook_session_id": session.id,
            "already_active": False,
        }
    except Exception as e:
        logger.exception("register_agent error")
        return {"status": "error", "detail": str(e)}


@router.post("/deregister-agent", status_code=200)
def deregister_agent(data: DeregisterAgentInput, db: Session = Depends(get_db)):
    """Mark a teammate's active hook session as completed."""
    try:
        session = db.scalars(
            select(HookSession)
            .where(HookSession.project_id == data.project_id)
            .where(HookSession.agent_id == data.agent_id)
            .where(HookSession.status == HookSessionStatus.active)
            .limit(1)
        ).first()
        if not session:
            return {"status": "ok", "message": "No active session found"}

        session.status = HookSessionStatus.completed
        session.end_time = datetime.now(timezone.utc)
        db.commit()
        return {
            "status": "ok",
            "session_id": session.session_id,
            "hook_session_id": session.id,
        }
    except Exception as e:
        logger.exception("deregister_agent error")
        return {"status": "error", "detail": str(e)}


@router.get("/sessions/{session_id}", response_model=HookSessionRead)
def get_hook_session(session_id: str, db: Session = Depends(get_db)):
    """Get a single hook session by its Claude Code session_id."""
    session = svc.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Hook session not found")
    return session
