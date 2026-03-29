# Path: app/routers/comments.py
# File: comments.py
# Created: 2026-03-29
# Purpose: Comment HTTP endpoints — list, get, create, delete
# Caller: app/main.py
# Callees: app/services/comment.py
# Data In: HTTP requests
# Data Out: JSON responses (CommentRead)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.comment import CommentCreate, CommentRead
from app.services import comment as svc

router = APIRouter(prefix="/api/comments", tags=["comments"])


@router.get("", response_model=list[CommentRead])
def list_comments(
    ticket_id: int | None = Query(None),
    author_agent_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_comments(db, ticket_id=ticket_id, author_agent_id=author_agent_id)


@router.get("/{comment_id}", response_model=CommentRead)
def get_comment(comment_id: int, db: Session = Depends(get_db)):
    comment = svc.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    return comment


@router.post("", response_model=CommentRead, status_code=201)
def create_comment(data: CommentCreate, db: Session = Depends(get_db)):
    return svc.create_comment(db, data)


@router.delete("/{comment_id}", status_code=204)
def delete_comment(comment_id: int, db: Session = Depends(get_db)):
    comment = svc.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    svc.delete_comment(db, comment)
