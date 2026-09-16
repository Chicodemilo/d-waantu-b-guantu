# Path: app/models/hook_session.py
# File: hook_session.py
# Created: 2026-04-09
# Purpose: HookSession ORM model — tracks Claude Code lifecycle hook sessions
# Caller: app/services/hook_tracking.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: HookSession, HookSessionStatus, HookSessionType
# Last Modified: 2026-09-16 (DWB-580: transcript_bytes, how much of the transcript the stored total accounts for)

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
    # DWB-335: link a hook session to its enclosing DWB session for rollup.
    # NULL allowed — historical rows predate the DWB session model and must
    # remain valid; future ingestion sets this when an open DWB session is
    # found for the project at hook receipt time.
    dwb_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dwb_sessions.id"), nullable=True, index=True
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # BigInteger (DWB-505): summand of the dwb_sessions token rollup; widened
    # from INT so a large per-session figure can never overflow the column.
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    token_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # DWB-580: how many BYTES of the transcript the recorded total accounts
    # for. The recapture sweep stats the file and skips it unless it has grown
    # past this, so a finished session costs one stat per cycle instead of a
    # full parse. NULL means "never swept", which reads as zero and lets the
    # first sweep look once.
    transcript_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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
