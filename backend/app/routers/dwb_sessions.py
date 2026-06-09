# Path: app/routers/dwb_sessions.py
# File: dwb_sessions.py
# Created: 2026-06-09
# Purpose: REST endpoints for DWB session open/close + read rollups (DWB-336, DWB-338)
# Caller: app/main.py
# Callees: app/services/dwb_session.py, app/services/dwb_session_rollup.py, app/schemas/dwb_session.py
# Data In: HTTP POST JSON bodies, GET query/path params
# Data Out: DwbSessionRead, DwbSessionListItem[], DwbSessionDetail (or 404/409)
# Last Modified: 2026-06-09

"""HTTP layer for DWB session lifecycle.

Endpoints intentionally thin: validate the body, delegate to
``app.services.dwb_session``, translate the (row, flag) tuples returned by
the service into HTTP semantics.

- ``POST /api/sessions/open``
    201 Created  -> new DwbSession (DwbSessionRead body)
    409 Conflict -> active session already exists (DwbSessionOpenConflict body)

- ``POST /api/sessions/{id}/close``
    200 OK       -> session closed (DwbSessionRead body) — also returned
                    on idempotent close (already-closed row, no-op)
    404 Not Found -> session_id not found

The service-layer close fn is shared with the idle sweeper (DWB-337) so
both code paths produce identically-shaped closed rows.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dwb_session import DwbSession
from app.models.project import Project
from app.schemas.dwb_session import (
    DwbSessionCloseRequest,
    DwbSessionDetail,
    DwbSessionListItem,
    DwbSessionOpenConflict,
    DwbSessionOpenRequest,
    DwbSessionRead,
)
from app.services import dwb_session as svc
from app.services import dwb_session_rollup as rollup

router = APIRouter(prefix="/api/sessions", tags=["dwb_sessions"])

# Second router exposes the project-scoped list under /api/projects/{id}/sessions
# without polluting projects.py with DWB-session-specific logic.
project_sessions_router = APIRouter(prefix="/api/projects", tags=["dwb_sessions"])


@router.post(
    "/open",
    status_code=201,
    response_model=DwbSessionRead,
    responses={
        409: {"model": DwbSessionOpenConflict, "description": "Active session exists"},
    },
)
def open_dwb_session(
    body: DwbSessionOpenRequest,
    db: Session = Depends(get_db),
):
    """Open a new DWB session for a project.

    Returns 201 with the new session row, or 409 with the active session's
    id + opened_at when another session is already open for this project.
    The single-active invariant is enforced at the DB layer too (composite
    UNIQUE on project_id + generated is_open marker — DWB-335), so this
    pre-check is for the friendly conflict body, not correctness.

    The conflict path returns a JSONResponse directly rather than the
    DwbSessionRead model, so FastAPI does not try to validate the conflict
    body against the success-path response_model.
    """
    new_session, existing = svc.open_session(
        db,
        project_id=body.project_id,
        opened_at=body.opened_at,
        open_method=body.open_method,
        open_phrase=body.open_phrase,
    )

    if existing is not None:
        conflict = DwbSessionOpenConflict(
            detail=(
                f"Project {body.project_id} already has an open DWB session "
                f"(id={existing.id}, opened_at={existing.opened_at.isoformat()})"
            ),
            active_session_id=existing.id,
            opened_at=existing.opened_at,
        )
        # Return as JSONResponse directly so the declared DwbSessionRead
        # response_model does not attempt to validate this conflict body.
        return JSONResponse(
            status_code=409,
            content=conflict.model_dump(mode="json"),
        )

    assert new_session is not None  # narrow for type checkers
    db.commit()
    db.refresh(new_session)
    return new_session


@router.post(
    "/{session_id}/close",
    status_code=200,
    response_model=DwbSessionRead,
)
def close_dwb_session(
    session_id: int,
    body: DwbSessionCloseRequest,
    db: Session = Depends(get_db),
):
    """Close an open DWB session (or no-op on already-closed).

    Idempotent: closing a row that was already closed returns 200 with the
    existing row unchanged. The router does NOT return 409 in that case —
    that would force callers to track local state to avoid retry noise.
    The idle sweeper (DWB-337) calls the same service function with
    ``close_method=idle_timeout`` + ``close_reason=idle`` and relies on the
    no-op semantics if a regex/AI close already won the race.
    """
    row = db.get(DwbSession, session_id)
    if row is None:
        raise HTTPException(404, f"DWB session {session_id} not found")

    was_already_closed = row.closed_at is not None
    svc.close_session(
        db,
        row,
        close_method=body.close_method,
        close_reason=body.close_reason,
        close_phrase=body.close_phrase,
        now=body.closed_at,
    )

    if not was_already_closed:
        db.commit()
        db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# DWB-338: read rollups
# ---------------------------------------------------------------------------


@project_sessions_router.get(
    "/{project_id}/sessions",
    response_model=list[DwbSessionListItem],
)
def list_project_sessions(
    project_id: int,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List DWB sessions for a project, most recent first.

    Returns a slim row per session (no rollup slices). For full detail
    including by_role / by_ticket / overhead, follow up with
    GET /api/sessions/{id}.

    404 when the project does not exist (separating "no project" from
    "project exists with zero sessions" so callers can distinguish a
    typo from a fresh project).
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(404, f"Project {project_id} not found")

    rows = list(
        db.execute(
            select(DwbSession)
            .where(DwbSession.project_id == project_id)
            .order_by(desc(DwbSession.opened_at))
            .limit(limit)
            .offset(offset)
        ).scalars()
    )

    return [
        DwbSessionListItem(
            id=r.id,
            opened_at=r.opened_at,
            closed_at=r.closed_at,
            total_tokens=r.total_tokens,
            total_time_seconds=r.total_time_seconds,
            status="open" if r.closed_at is None else "closed",
        )
        for r in rows
    ]


@router.get(
    "/{session_id}",
    response_model=DwbSessionDetail,
)
def get_dwb_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
):
    """Full session detail: meta + totals + by_role + by_ticket + overhead.

    For closed sessions the totals reflect the frozen stored fields. For
    open sessions the totals are live partials: workers' tokens that have
    already landed via SubagentStop are present, but the TL's own tokens
    (which only attribute on SessionEnd) are not yet reflected. The
    ``live`` flag in the response signals which world the caller is
    looking at.
    """
    row = db.get(DwbSession, session_id)
    if row is None:
        raise HTTPException(404, f"DWB session {session_id} not found")

    is_open = row.closed_at is None

    by_role = rollup.compute_by_role(db, row)
    by_ticket = rollup.compute_by_ticket(db, row)
    tl_overhead, pm_overhead = rollup.compute_overhead_deltas(db, row)

    if is_open:
        live_tokens, live_time = rollup.compute_live_totals(db, row)
        total_tokens = live_tokens
        total_time_seconds = live_time
    else:
        total_tokens = row.total_tokens
        total_time_seconds = row.total_time_seconds

    return DwbSessionDetail(
        id=row.id,
        project_id=row.project_id,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        open_phrase=row.open_phrase,
        close_phrase=row.close_phrase,
        open_method=row.open_method,
        close_method=row.close_method,
        close_reason=row.close_reason,
        status="open" if is_open else "closed",
        live=is_open,
        total_tokens=total_tokens,
        total_time_seconds=total_time_seconds,
        by_role=by_role,
        by_ticket=by_ticket,
        tl_overhead_tokens=tl_overhead,
        pm_overhead_tokens=pm_overhead,
    )
