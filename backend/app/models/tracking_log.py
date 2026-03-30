# Path: app/models/tracking_log.py
# File: tracking_log.py
# Created: 2026-03-30
# Purpose: TrackingLog ORM model — start/stop/token events for time and token tracking
# Caller: app/services/tracking.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: TrackingLog
# Last Modified: 2026-03-30

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrackingLog(Base):
    __tablename__ = "tracking_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id"), nullable=True, index=True
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    sprint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
