# Path: app/models/failure_record.py
# File: failure_record.py
# Created: 2026-03-29
# Purpose: FailureRecord ORM model — failure analysis tracking
# Caller: app/services/failure_record.py, ticket.py, test_result.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: FailureRecord
# Last Modified: 2026-03-29

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FailureRecord(Base):
    __tablename__ = "failure_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sprint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    logged_by_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    failure_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship()  # noqa: F821
    ticket: Mapped["Ticket | None"] = relationship(back_populates="failure_records")  # noqa: F821
    sprint: Mapped["Sprint"] = relationship()  # noqa: F821
    agent: Mapped["Agent"] = relationship(foreign_keys=[agent_id])  # noqa: F821
    logged_by_agent: Mapped["Agent"] = relationship(foreign_keys=[logged_by_agent_id])  # noqa: F821
