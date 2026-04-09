# Path: app/models/error_log.py
# File: error_log.py
# Created: 2026-04-09
# Purpose: ErrorLog ORM model for system-wide error tracking
# Caller: app/routers/errors.py, app/middleware/error_logger.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: ErrorLog, ErrorSource
# Last Modified: 2026-04-09

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ErrorSource(str, enum.Enum):
    backend = "backend"
    frontend = "frontend"
    hook = "hook"


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[ErrorSource] = mapped_column(
        Enum(ErrorSource), nullable=False, default=ErrorSource.backend
    )
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    function_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
