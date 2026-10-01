# Path: app/models/hook_session.py
# File: hook_session.py
# Created: 2026-04-09
# Purpose: HookSession ORM model — tracks Claude Code lifecycle hook sessions
# Caller: app/services/hook_tracking.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: HookSession, HookSessionStatus, HookSessionType
# Last Modified: 2026-09-29 (DWB-584: prompt_count, storage for the DWB-590 top-off counter)

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


# DWB-581: how a session came to carry its ticket_id. Lives here rather than in
# the service because the service writes it, the schema exposes it, and the
# tests assert on it: one definition all three import.
#
# The point is that a GUESS and a FACT are indistinguishable in the row
# afterwards. ticket_id alone says which ticket; it never said how confident we
# were, so an investigator looking at a strange per-ticket number had no way to
# separate "the ticket was already assigned when we looked" from "a ticket
# claimed this session later because it was the best available guess".
TICKET_SOURCE_RESOLVED_AT_START = "resolved_at_start"
"""The lookup found the ticket when the row was created: it was already
assigned to this agent. A fact."""

TICKET_SOURCE_RESOLVED_LATER = "resolved_later"
"""A later hook event filled a NULL. The same lookup, run later. Also a fact,
and it additionally tells you the attribution arrived after work had started."""

TICKET_SOURCE_CLAIMED_BY_TICKET = "claimed_by_ticket"
"""The ticket side pushed it (DWB-576). A BEST GUESS, and the only one of the
three that can be wrong: a session claimed by the most recent assignment may
belong to earlier work in the same sprint."""

TICKET_SOURCES = (
    TICKET_SOURCE_RESOLVED_AT_START,
    TICKET_SOURCE_RESOLVED_LATER,
    TICKET_SOURCE_CLAIMED_BY_TICKET,
)
"""NULL is deliberately not in this tuple. A NULL means "we do not know how
this row got its ticket", which is the honest reading for every row written
before this column existed and for every row that never got a ticket at all."""


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
    # DWB-581: which mechanism supplied ticket_id. See TICKET_SOURCES above.
    # String rather than Enum on purpose: DwbOpenMethod still carries
    # `ai_classifier` as a permanent tombstone because DWB-402 retired that
    # path and historical rows had to keep loading. Attribution paths are a
    # vocabulary we keep extending, so the looser type avoids paying that
    # again every time one is added or retired.
    ticket_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    # DWB-584 (storage for DWB-590's top-off): how many user prompts this
    # Claude Code session has taken. STORED, not derived, and that was checked
    # rather than defaulted: nothing in the schema records a prompt. This table
    # is one row per session, not per prompt, and handle_user_prompt writes no
    # row on any of its noop paths, so there is no existing count and no trace
    # to count from.
    #
    # Keyed by session_id, which the hook payload already carries, making the
    # counter per Claude Code session and therefore per agent - the same unit
    # the top-off is injected into.
    #
    # NOT NULL default 0, so an existing row reads as "no prompts counted yet"
    # rather than NULL. One edge belongs to DWB-590, not here: a prompt arriving
    # before SessionStart has been processed has no row to count against, and
    # that case needs a defined behaviour rather than an exception.
    #
    # Unrelated to memory mode. Top-off is orthogonal to human_memory by ruling.
    prompt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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
