# Path: app/models/inter_agent_message.py
# File: inter_agent_message.py
# Created: 2026-06-24
# Purpose: InterAgentMessage ORM model (DWB-446) - one row per agent-to-agent
#          message captured from the SendMessage hook (DWB-447). Foundation of
#          Epic 35 "Inter-Agent Comms Capture & Log".
# Caller: app/services/hook_tracking.py, app/routers/agent_messages.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: InterAgentMessage
# Last Modified: 2026-06-24

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InterAgentMessage(Base):
    """A single agent-to-agent message captured from the SendMessage hook.

    DWB-446 foundation. The sender is resolved from the Claude Code
    ``session_id`` via the same resolver token attribution uses
    (hook_tracking); the recipient is resolved best-effort by name within the
    project. Both FK ids are nullable - the ``*_name`` varchars always carry
    the human-readable label so the log stays readable even when a resolve
    misses.

    ``dwb_session_id`` is DISPLAY-ONLY: it is stamped when a session is open but
    is never used to purge. The age sweep (DWB-449) keys off ``created_at``
    alone, so a message outlives the session it was sent in.
    """

    __tablename__ = "inter_agent_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False
    )
    # Display-only. NOT used for purge - the age sweep keys off created_at.
    dwb_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dwb_sessions.id"), nullable=True
    )
    from_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True
    )
    from_agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
