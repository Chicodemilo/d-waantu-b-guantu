# Path: app/routers/tickets.py
# File: tickets.py
# Created: 2026-03-29
# Purpose: Ticket HTTP endpoints — CRUD, history, tokens, token-attribution
# Caller: app/main.py
# Callees: app/services/ticket.py
# Data In: HTTP requests
# Data Out: JSON responses (TicketRead, StatusHistoryRead, attribution dict)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ticket import TicketStatus, TicketType
from app.schemas.status_history import StatusHistoryRead
from app.schemas.ticket import TicketCreate, TicketRead, TicketTokenIncrement, TicketUpdate
from app.services import ticket as svc

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketRead])
def list_tickets(
    project_id: int | None = Query(None),
    sprint_id: int | None = Query(None),
    epic_id: int | None = Query(None),
    assigned_agent_id: int | None = Query(None),
    status: TicketStatus | None = Query(None),
    ticket_type: TicketType | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_tickets(
        db,
        project_id=project_id,
        sprint_id=sprint_id,
        epic_id=epic_id,
        assigned_agent_id=assigned_agent_id,
        status=status,
        ticket_type=ticket_type,
    )


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.post("", response_model=TicketRead, status_code=201)
def create_ticket(data: TicketCreate, db: Session = Depends(get_db)):
    return svc.create_ticket(db, data)


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: int, data: TicketUpdate, db: Session = Depends(get_db)
):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return svc.update_ticket(db, ticket, data)


@router.get("/{ticket_id}/history", response_model=list[StatusHistoryRead])
def get_ticket_history(ticket_id: int, db: Session = Depends(get_db)):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return svc.get_ticket_history(db, ticket_id)


@router.post("/{ticket_id}/tokens", response_model=TicketRead)
def increment_ticket_tokens(
    ticket_id: int, data: TicketTokenIncrement, db: Session = Depends(get_db)
):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return svc.increment_tokens(db, ticket, data.tokens_used, data.time_spent_seconds, source=data.source)


@router.get("/{ticket_id}/token-attribution")
def get_token_attribution(ticket_id: int, db: Session = Depends(get_db)):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return svc.get_token_attribution(db, ticket)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    svc.delete_ticket(db, ticket)
