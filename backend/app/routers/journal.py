# Path: app/routers/journal.py
# File: journal.py
# Created: 2026-09-29 (DWB-587)
# Purpose: Journal HTTP endpoints - POST /api/journal appends, GET /api/journal
#          searches by tags, date range and term. There is no full-dump route.
# Caller: app/main.py
# Callees: app/services/journal.py
# Data In: HTTP requests
# Data Out: JSON responses (JournalEntryRead, JournalSearchResponse)
# Last Modified: 2026-09-29 (DWB-587)

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.journal import (
    JournalEntryCreate,
    JournalEntryRead,
    JournalSearchResponse,
)
from app.services import journal as svc

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.post("", response_model=JournalEntryRead, status_code=201)
def create_journal_entry(data: JournalEntryCreate, db: Session = Depends(get_db)):
    """Append one journal entry (DWB-587, spec section 5).

    Append-only: there is no update and no delete route. Section 7 hard rule 4
    makes the journal the place things GO on their way out of memory, which is
    what makes an eviction recoverable; a journal that can be edited or emptied
    cannot carry that guarantee.

    Errors: 400 empty body, 404 unknown agent.
    """
    try:
        entry = svc.create_entry(
            db,
            agent_id=data.agent_id,
            body=data.body,
            tags=data.tags,
        )
    except svc.JournalError as e:
        raise HTTPException(404 if e.code == "agent_not_found" else 400, e.detail)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("", response_model=JournalSearchResponse)
def search_journal(
    db: Session = Depends(get_db),
    agent_id: int | None = Query(
        default=None,
        description=(
            "Scope to one agent. NOT a filter: it narrows whose journal is read, "
            "not which question is asked, so it does not on its own satisfy the "
            "filter requirement below."
        ),
    ),
    tags: list[str] | None = Query(
        default=None,
        description="Match entries carrying ANY of these tags (repeat the param).",
    ),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    term: str | None = Query(default=None, description="Substring of the entry body."),
    limit: int = Query(default=svc.DEFAULT_LIMIT, ge=1, le=svc.MAX_LIMIT),
):
    """Search the journal. At least one of tags / date_from / date_to / term.

    A REQUEST WITH NO FILTER IS REFUSED (422). This is the acceptance criterion,
    not a nicety: spec section 5 rules that retrieval is "never a full read - it
    is 'I think that was about two weeks ago, to do with Greg, or ssh'. Tags +
    date + term." Memory must shrink while the journal may sprawl, so an
    unfiltered read pulls the sprawl into context and the cost model that makes
    the journal free collapses.

    A default page size does NOT satisfy this and `limit` is not an alternative
    to a filter: page one of everything is still a read nobody asked a question
    to get.

    EVERY ENTRY RETURNED HAS ITS retrieval_count INCREMENTED, server-side, and
    no request parameter suppresses it. Retrieval is the reinforcement signal
    (section 5), and a caller able to read without being counted is a caller
    able to make that signal lie. The counts in the response are the values
    AFTER this retrieval.

    Errors: 422 no filter supplied, 400 bad limit.
    """
    try:
        result = svc.search_entries(
            db,
            agent_id=agent_id,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
            term=term,
            limit=limit,
        )
    except svc.JournalError as e:
        # 422 for the missing filter: the request is well-formed but
        # unprocessable, and it is the same status FastAPI already uses for a
        # request that does not carry what the endpoint needs.
        raise HTTPException(422 if e.code == "filter_required" else 400, e.detail)
    db.commit()
    return result
