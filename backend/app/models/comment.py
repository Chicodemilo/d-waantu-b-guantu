# Path: app/models/comment.py
# File: comment.py
# Created: 2026-03-29
# Purpose: Comment ORM model — ticket discussion entries
# Caller: app/services/comment.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Comment
# Last Modified: 2026-03-29

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship(back_populates="comments")  # noqa: F821
    author_agent: Mapped["Agent"] = relationship(back_populates="comments")  # noqa: F821
