# Path: app/routers/dwb_sessions.py
# File: dwb_sessions.py
# Created: 2026-06-09
# Purpose: REST endpoints for DWB session open/close/reopen + read rollups + cross-session search (DWB-336, DWB-338, DWB-346 list aggregates + headline, DWB-353 ad_hoc bucket, DWB-395 reopen, DWB-493 summary+keywords on list/detail, DWBG-011 GET /api/sessions/search)
# Caller: app/main.py
# Callees: app/services/dwb_session.py, app/services/dwb_session_rollup.py, app/services/dwb_session_search.py, app/schemas/dwb_session.py, app/models/entity_keyword.py
# Data In: HTTP POST JSON bodies, GET query/path params
# Data Out: DwbSessionRead, DwbSessionListItem[], DwbSessionDetail, DwbSessionSearchResult[] (or 404/409/422)
# Last Modified: 2026-06-25 (DWBG-014 generate-narrative endpoint; DWBG-016 GET /api/sessions/recent)

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

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dwb_session import DwbCloseMethod, DwbSession
from app.models.entity_keyword import EntityKeyword
from app.services import agent_consolidation as consolidation_svc
from app.models.project import Project
from app.schemas.dwb_session import (
    DwbSessionCloseRequest,
    DwbSessionDetail,
    DwbSessionKeyword,
    DwbSessionListItem,
    DwbSessionNarrativeResult,
    DwbSessionOpenConflict,
    DwbSessionOpenRequest,
    DwbSessionRead,
    DwbSessionRecentItem,
    DwbSessionSearchResult,
)
from app.services import dwb_session as svc
from app.services import dwb_session_rollup as rollup
from app.services import dwb_session_search as search_svc

router = APIRouter(prefix="/api/sessions", tags=["dwb_sessions"])


def _keywords_by_session(
    db: Session, session_ids: list[int]
) -> dict[int, list[DwbSessionKeyword]]:
    """Batch-fetch session keywords (DWB-493): ONE query over entity_keywords
    for all given session ids, grouped in Python and sorted weight desc (then
    keyword asc for a stable tie-break). Avoids an N+1 across a sessions page.
    Returns {session_id: [DwbSessionKeyword, ...]}; ids with no rows are absent.
    """
    if not session_ids:
        return {}
    rows = db.execute(
        select(EntityKeyword)
        .where(EntityKeyword.entity_type == "dwb_session")
        .where(EntityKeyword.entity_id.in_(session_ids))
        .order_by(desc(EntityKeyword.weight), EntityKeyword.keyword.asc())
    ).scalars().all()
    out: dict[int, list[DwbSessionKeyword]] = {}
    for r in rows:
        out.setdefault(r.entity_id, []).append(
            DwbSessionKeyword(keyword=r.keyword, weight=r.weight)
        )
    return out

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

    # Headline is REQUIRED on the conscious-bot close methods (ai_confident /
    # ai_asked) — those are the only closes where an agent (Archie) is the
    # actor and can summarise the session. The machine-driven layers
    # (regex / slash / ai_classifier / idle_timeout) carry a fixed payload
    # with no summariser and stay exempt. An already-closed row is an
    # idempotent no-op and is not re-validated. The message is written for the
    # closing agent: it carries the session window so the bot summarises the
    # right span.
    needs_headline = not was_already_closed and body.close_method in (
        DwbCloseMethod.ai_confident,
        DwbCloseMethod.ai_asked,
    )
    if needs_headline and not (body.headline and body.headline.strip()):
        start = row.opened_at.strftime("%Y-%m-%d %H:%M UTC")
        end = (body.closed_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
        raise HTTPException(
            422,
            (
                f"You must provide a headline: 5 to 10 words of what was done "
                f"in this session from {start} to {end}. It does not need to be "
                f"a full complete sentence, it can just be descriptive words. "
                f"If you need to recall what happened, check your own session "
                f"context first, then GET /api/sessions/{session_id} for the "
                f"rollup (tickets completed, work by ticket/role) and "
                f"GET /api/tracking/summary?project_id={row.project_id} for "
                f"token/time activity in the window."
            ),
        )

    # Compaction gate (parallel, autonomous, HARD). On the conscious-bot
    # closes the whole project's spawn-loaded docs must be within ceiling
    # before the session can close. The TL fans this out: every agent compacts
    # its OWN memory files at once via POST /api/agents/{id}/memory/compact, and
    # the TL compacts the shared root docs (HANDOFF/ARCHITECTURE/README) + its
    # own. The close is refused until all are within budget — the refusal IS
    # the gate. idle/regex/slash/classifier closes are exempt (no live team to
    # compact). Same method scoping as the headline gate above.
    # DWB-400: the compaction gate is opt-in per project. It only blocks the
    # close on a conscious-bot close (ai_confident / ai_asked) when the project
    # has force_consolidation enabled. Default OFF means the close is never
    # blocked on doc ceilings, matching the sprint-close consolidation gate.
    project = db.get(Project, row.project_id) if needs_headline else None
    if needs_headline and project and project.force_consolidation:
        over = consolidation_svc.over_ceiling_files_for_project(db, project)
        if over:
            by_owner: dict[str, list[str]] = {}
            for f in over:
                owner = f["agent_name"] or "team-lead (shared root docs)"
                by_owner.setdefault(owner, []).append(
                    f"{f['name']} (~{f['tokens']}/{f['ceiling']} tok)"
                )
            offenders = "; ".join(
                f"{owner} -> {', '.join(items)}"
                for owner, items in sorted(by_owner.items())
            )
            raise HTTPException(
                422,
                (
                    "Compaction gate: this session cannot close until the "
                    "over-ceiling docs below are compacted. Have every owner "
                    "compact their files IN PARALLEL, now, without waiting to be "
                    "asked — each agent rewrites its own memory files leaner and "
                    "submits via POST /api/agents/{agent_id}/memory/compact "
                    "{file, content}; the team-lead compacts the shared root "
                    "docs (HANDOFF / ARCHITECTURE / README). Then retry the "
                    f"close. Over ceiling: {offenders}"
                ),
            )

    svc.close_session(
        db,
        row,
        close_method=body.close_method,
        close_reason=body.close_reason,
        close_phrase=body.close_phrase,
        now=body.closed_at,
        headline=body.headline,
        narrative=body.narrative,  # DWBG-007: TL-authored interpretive narrative
    )

    if not was_already_closed:
        db.commit()
        db.refresh(row)
    return row


@router.post(
    "/{session_id}/reopen",
    status_code=200,
    response_model=DwbSessionRead,
    responses={
        409: {
            "model": DwbSessionOpenConflict,
            "description": "Another session is already open for this project",
        },
    },
)
def reopen_dwb_session(
    session_id: int,
    db: Session = Depends(get_db),
):
    """Reopen a closed DWB session (DWB-395).

    Nulls closed_at / close_method / close_reason / close_phrase and returns
    the reopened row. ``is_open`` is a generated STORED column that recomputes
    from closed_at, so nulling closed_at is sufficient to flip the single-active
    marker.

    This endpoint replaces the manual DB null-out that has been done by hand
    several times after a false close (e.g. TL prose tripping the Layer-1 close
    catalogue).

    Status semantics:
      200 OK       -> session reopened (DwbSessionRead body). Also returned on
                      the idempotent no-op when the row was already open.
      404 Not Found -> session_id does not exist.
      409 Conflict -> a DIFFERENT session is already open for this project;
                      the body surfaces the blocking session's id + opened_at +
                      headline. The single-active invariant forbids two open
                      sessions per project, so the existing one must be closed
                      first.
    """
    row = db.get(DwbSession, session_id)
    if row is None:
        raise HTTPException(404, f"DWB session {session_id} not found")

    reopened, conflict = svc.reopen_session(db, row)

    if conflict is not None:
        body = DwbSessionOpenConflict(
            detail=(
                f"Project {row.project_id} already has an open DWB session "
                f"(id={conflict.id}, opened_at={conflict.opened_at.isoformat()}); "
                f"close it before reopening session {session_id}"
            ),
            active_session_id=conflict.id,
            opened_at=conflict.opened_at,
            headline=conflict.headline,
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))

    assert reopened is not None  # narrow for type checkers
    db.commit()
    db.refresh(reopened)
    return reopened


# ---------------------------------------------------------------------------
# DWBG-014: on-demand / regenerate session narrative
# ---------------------------------------------------------------------------


@router.post(
    "/{session_id}/generate-narrative",
    status_code=200,
    response_model=DwbSessionNarrativeResult,
)
def generate_dwb_session_narrative(
    session_id: int,
    db: Session = Depends(get_db),
):
    """Generate (or regenerate) the LLM wrap-up narrative for a session (DWBG-014).

    Builds the DWBG-013 work record, summarizes it via the Claude API, redacts
    (DWBG-008), and persists with narrative_author='summarizer'. Works on open or
    closed sessions (regenerate is allowed even after close). Always overwrites
    any existing narrative with the fresh run - this is the explicit "regenerate"
    action, distinct from the auto-on-close path that only fills a gap.

    Best-effort: a skip (no ANTHROPIC_API_KEY, no agent evidence in the window, an
    API error, or an unparseable response) returns 200 with generated=False rather
    than an error, so the UI button degrades gracefully. 404 only when the session
    does not exist."""
    row = db.get(DwbSession, session_id)
    if row is None:
        raise HTTPException(404, f"DWB session {session_id} not found")

    narrative = svc.generate_session_narrative(db, row)
    if narrative is not None:
        db.commit()
        db.refresh(row)

    return DwbSessionNarrativeResult(
        session_id=row.id,
        generated=narrative is not None,
        narrative_author=row.narrative_author,
        narrative_generated_at=row.narrative_generated_at,
        narrative=row.narrative,
    )


# ---------------------------------------------------------------------------
# DWBG-011: cross-session search
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=list[DwbSessionSearchResult],
)
def search_dwb_sessions(
    q: str = Query(..., description="FULLTEXT query over session prose"),
    project_id: int | None = Query(None, description="Scope to one project; omit for cross-project"),
    agent_id: int | None = Query(None, description="Only sessions a given agent worked"),
    epic_id: int | None = Query(None, description="Only sessions where a ticket on this epic completed in-window"),
    date_from: datetime | None = Query(None, alias="from", description="opened_at >= this (ISO 8601)"),
    date_to: datetime | None = Query(None, alias="to", description="opened_at <= this (ISO 8601)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Ranked cross-session search over session write-up prose (DWBG-011).

    `q` runs a MySQL FULLTEXT MATCH over dwb_sessions.search_text (DWBG-010:
    headline + summary + narrative flattened into one indexed column). Results
    rank by FULLTEXT relevance, boosted by the summed entity_keywords.weight for
    keywords whose term matched the query, with recency (opened_at) as the
    tiebreaker. Search is cross-project when `project_id` is omitted.

    Facets (all optional, ANDed): project_id, agent_id (a linked hook_session),
    epic_id (a ticket on that epic completed in the session window), and a
    from/to date range on opened_at.

    `q` must be non-blank: a missing/empty/whitespace-only query is a 422. A
    valid-but-unmatched query returns an empty list (200). The endpoint reuses
    the DWB-493 batched keyword read for the keyword chips so there is no N+1
    across the result page.

    Only agent-produced prose is indexed (DWB-351 / DWBG-003); no user prompt
    text is searchable.
    """
    if not q or not q.strip():
        raise HTTPException(422, "Search query 'q' must not be empty or blank")

    hits = search_svc.search_sessions(
        db,
        q=q.strip(),
        project_id=project_id,
        agent_id=agent_id,
        epic_id=epic_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    if not hits:
        return []

    # DWB-493 batched keyword read for the chips - one query for the whole page.
    keywords_map = _keywords_by_session(db, [h["id"] for h in hits])

    return [
        DwbSessionSearchResult(
            id=h["id"],
            project_id=h["project_id"],
            headline=h["headline"],
            opened_at=h["opened_at"],
            closed_at=h["closed_at"],
            total_tokens=h["total_tokens"],
            relevance=h["relevance"],
            keyword_boost=h["keyword_boost"],
            score=h["score"],
            snippet=h["snippet"],
            keywords=keywords_map.get(h["id"], []),
        )
        for h in hits
    ]


# ---------------------------------------------------------------------------
# DWBG-016 dependency: cross-project recent sessions (Recall page default view)
# ---------------------------------------------------------------------------


@router.get(
    "/recent",
    response_model=list[DwbSessionRecentItem],
)
def recent_dwb_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Cross-project recent DWB sessions, newest-first (DWBG-016 dependency).

    Slim rows in the same shape as the search result rows (id, project_id,
    headline, opened_at, closed_at, total_tokens, keywords) so Freddie's Recall
    page can show recent sessions by default with the same card component it uses
    for search hits. Ordered by opened_at DESC (id DESC tiebreak for determinism)
    with limit/offset paging.

    Registered before the `/{session_id}` catch-all so "recent" is not parsed as
    a session id. Reuses the DWB-493 batched keyword read so there is no N+1
    across the page."""
    rows = list(
        db.execute(
            select(DwbSession)
            .order_by(desc(DwbSession.opened_at), desc(DwbSession.id))
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    if not rows:
        return []

    keywords_map = _keywords_by_session(db, [r.id for r in rows])
    return [
        DwbSessionRecentItem(
            id=r.id,
            project_id=r.project_id,
            headline=r.headline,
            opened_at=r.opened_at,
            closed_at=r.closed_at,
            total_tokens=r.total_tokens,
            keywords=keywords_map.get(r.id, []),
        )
        for r in rows
    ]


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

    Returns a slim row per session plus DWB-346 per-row aggregates:
    tickets_made / tickets_completed / agents_active / open_method /
    close_method / headline / ticket_summary. For full detail including
    by_role / by_ticket / overhead, follow up with GET /api/sessions/{id}.

    404 when the project does not exist (separating "no project" from
    "project exists with zero sessions" so callers can distinguish a
    typo from a fresh project).

    Backwards-compatibility: the original six fields (id, opened_at,
    closed_at, total_tokens, total_time_seconds, status) keep their old
    shape and values. DWB-346 aggregates are additive only.
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

    # DWB-493: batch-fetch keywords for the whole page in one query (no N+1).
    keywords_map = _keywords_by_session(db, [r.id for r in rows])

    items: list[DwbSessionListItem] = []
    for r in rows:
        agg = rollup.compute_list_aggregates(db, r)
        ad_hoc_tokens, ad_hoc_seconds = rollup.compute_ad_hoc_bucket(db, r)
        items.append(
            DwbSessionListItem(
                id=r.id,
                opened_at=r.opened_at,
                closed_at=r.closed_at,
                total_tokens=r.total_tokens,
                total_time_seconds=r.total_time_seconds,
                status="open" if r.closed_at is None else "closed",
                headline=r.headline,
                tickets_made=agg["tickets_made"],
                tickets_completed=agg["tickets_completed"],
                agents_active=agg["agents_active"],
                open_method=r.open_method,
                close_method=r.close_method,
                ticket_summary=agg["ticket_summary"],
                ad_hoc_overhead_tokens=ad_hoc_tokens,
                ad_hoc_overhead_seconds=ad_hoc_seconds,
                summary=r.summary,
                keywords=keywords_map.get(r.id, []),
            )
        )
    return items


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
    ad_hoc_tokens, ad_hoc_seconds = rollup.compute_ad_hoc_bucket(db, row)
    # DWB-493: weighted keywords for this one session, sorted weight desc.
    keywords = _keywords_by_session(db, [row.id]).get(row.id, [])

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
        headline=row.headline,
        summary=row.summary,
        narrative=row.narrative,
        narrative_author=row.narrative_author,
        narrative_generated_at=row.narrative_generated_at,
        keywords=keywords,
        status="open" if is_open else "closed",
        live=is_open,
        total_tokens=total_tokens,
        total_time_seconds=total_time_seconds,
        by_role=by_role,
        by_ticket=by_ticket,
        tl_overhead_tokens=tl_overhead,
        pm_overhead_tokens=pm_overhead,
        ad_hoc_overhead_tokens=ad_hoc_tokens,
        ad_hoc_overhead_seconds=ad_hoc_seconds,
    )
