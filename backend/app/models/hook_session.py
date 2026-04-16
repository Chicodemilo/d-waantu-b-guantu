# Path: app/models/hook_session.py
# File: hook_session.py
# Created: 2026-04-09
# Purpose: HookSession ORM model — tracks Claude Code lifecycle hook sessions
# Caller: app/services/hook_tracking.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: HookSession, HookSessionStatus, HookSessionType
# Last Modified: 2026-04-09

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HookSessionStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    error = "error"


class HookSessionType(str, enum.Enum):
    main = "main"
    teammate = "teammate"
    subagent = "subagent"


class HookSession(Base):
    __tablename__ = "hook_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    transcript_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sprint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=True, index=True
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[HookSessionStatus] = mapped_column(
        Enum(HookSessionStatus), nullable=False, default=HookSessionStatus.active
    )
    session_type: Mapped[HookSessionType] = mapped_column(
        Enum(HookSessionType), nullable=False, default=HookSessionType.teammate
    )
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hook_event: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    ticket: Mapped["Ticket | None"] = relationship(back_populates="hook_sessions")  # noqa: F821
