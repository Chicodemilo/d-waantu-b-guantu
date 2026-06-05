# Path: app/models/agent_consolidation_ack.py
# File: agent_consolidation_ack.py
# Created: 2026-06-04
# Purpose: AgentConsolidationAck ORM model — per-agent, per-sprint ack of file consolidation
# Caller: app/services/agent_consolidation.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: AgentConsolidationAck
# Last Modified: 2026-06-05

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentConsolidationAck(Base):
    __tablename__ = "agent_consolidation_acks"
    __table_args__ = (
        UniqueConstraint("agent_id", "sprint_id", name="uq_consolidation_agent_sprint"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    sprint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=False, index=True
    )
    acked_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # DWB-328: per-file override map {filename: reason} — populated when the
    # agent justifies leaving an owned over-ceiling file as-is. Null if the
    # ack was a clean trim (no over-ceiling violations).
    overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)
