# Path: app/models/test_result.py
# File: test_result.py
# Created: 2026-03-29
# Purpose: TestResult ORM model — test run outcomes
# Caller: app/services/test_result.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: TestResult
# Last Modified: 2026-03-29

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.sprint import Sprint
    from app.models.ticket import Ticket


class TestStatus(str, enum.Enum):
    passed = "passed"
    failed = "failed"
    error = "error"


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    suite: Mapped[str] = mapped_column(String(100), nullable=False)
    total_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[TestStatus] = mapped_column(
        Enum(TestStatus), nullable=False, default=TestStatus.passed
    )
    sprint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=True, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(100), nullable=False, default="manual")
    triggered_context: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="test_results")  # noqa: F821
    sprint: Mapped["Sprint | None"] = relationship()  # noqa: F821
    ticket: Mapped["Ticket | None"] = relationship(back_populates="test_results")  # noqa: F821
