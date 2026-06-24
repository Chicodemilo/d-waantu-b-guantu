# Path: app/models/alert.py
# File: alert.py
# Created: 2026-03-29
# Purpose: Alert ORM model with severity/status enums
# Caller: app/services/alert.py, sprint.py, ticket.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Alert, AlertSeverity, AlertStatus, AlertCategory
# Last Modified: 2026-06-24 (DWB-462: category taxonomy comms/scoring/actionable)

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class AlertCategory(str, enum.Enum):
    """DWB-462: alerts-vs-actions taxonomy (epic 37).

    - comms: inter-agent communication surfaced as an alert (TL-channel pings).
    - scoring: a reputation carrot/stick the team should see.
    - actionable: something requires action (missing gate file, rework).

    Things that are NOT real alerts (peer scoring, sprint-close notice,
    test-run requested) are demoted to the activity feed in DWB-463 and stop
    creating Alert rows entirely.
    """

    comms = "comms"
    scoring = "scoring"
    actionable = "actionable"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    raised_by_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    # DWB-426: optional recipient for per-agent broadcast notifications (e.g.
    # scoring carrot/stick alerts). NULL = a project-wide alert with no specific
    # recipient (all historical alerts + the stale/rework/test alerts).
    recipient_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity), nullable=False, default=AlertSeverity.info
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus), nullable=False, default=AlertStatus.open
    )
    # DWB-462: taxonomy bucket. Defaults to actionable so any creation path
    # that doesn't set it explicitly still carries a valid category (the
    # status open_alerts count and the /api/alerts filter both key off it).
    category: Mapped[AlertCategory] = mapped_column(
        Enum(AlertCategory),
        nullable=False,
        default=AlertCategory.actionable,
        server_default=AlertCategory.actionable.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="alerts")  # noqa: F821
    raised_by_agent: Mapped["Agent"] = relationship(  # noqa: F821
        back_populates="raised_alerts", foreign_keys=[raised_by_agent_id]
    )
    ticket: Mapped["Ticket | None"] = relationship(back_populates="alerts")  # noqa: F821
