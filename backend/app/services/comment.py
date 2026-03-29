# Path: app/services/comment.py
# File: comment.py
# Created: 2026-03-29
# Purpose: Comment CRUD operations
# Caller: app/routers/comments.py
# Callees: app/models/comment.py
# Data In: db: Session, CommentCreate
# Data Out: list[Comment], Comment
# Last Modified: 2026-03-29

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.comment import Comment
from app.schemas.comment import CommentCreate


def list_comments(
    db: Session,
    ticket_id: int | None = None,
    author_agent_id: int | None = None,
) -> list[Comment]:
    stmt = select(Comment)
    if ticket_id:
        stmt = stmt.where(Comment.ticket_id == ticket_id)
    if author_agent_id:
        stmt = stmt.where(Comment.author_agent_id == author_agent_id)
    stmt = stmt.order_by(Comment.created_at.desc())
    return list(db.scalars(stmt).all())


def get_comment(db: Session, comment_id: int) -> Comment | None:
    return db.get(Comment, comment_id)


def create_comment(db: Session, data: CommentCreate) -> Comment:
    comment = Comment(**data.model_dump())
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(db: Session, comment: Comment) -> None:
    db.delete(comment)
    db.commit()
