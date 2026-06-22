# Path: app/models/tool_action.py
# File: tool_action.py
# Created: 2026-06-22
# Purpose: ToolAction ORM model (DWB-417) - deterministic capture of agent tool
#          invocations from the Claude Code PostToolUse hook. Foundation row for
#          the agent-scoring epic; siblings (DWB-418..423) populate target +
#          tool_metadata and per-tool event_type classification.
# Caller: app/services/hook_tracking.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: ToolAction
# Last Modified: 2026-06-22

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ToolAction(Base):
    """A single agent tool invocation captured from the PostToolUse hook.

    DWB-417 foundation: one row per tool use. Context (agent/dwb_session/ticket)
    is resolved from the Claude Code ``session_id`` the same way hook_tracking
    resolves session-end attribution; any of those FKs may be NULL when the
    session can't be resolved (delivery-gap tolerance - never block the hook).

    ``target`` and ``tool_metadata`` stay NULL on this foundation ticket: the
    per-tool classification (Write/Edit file paths, SendMessage recipients,
    Task child agents, ...) is the sibling tickets' job. The row shape and the
    resolution path are built to support that extension.
    """

    __tablename__ = "tool_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True, index=True
    )
    # The Claude Code hook session_id string. NOT unique - one session emits
    # many tool actions. Indexed for per-session rollups.
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dwb_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dwb_sessions.id"), nullable=True, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Generic per-tool target slot (file path, to-agent, child-agent). NULL on
    # this foundation ticket; siblings fill it.
    target: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Generic verb. Default 'tool_use'; siblings refine to per-tool classes.
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="tool_use", server_default="tool_use"
    )
    tool_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
