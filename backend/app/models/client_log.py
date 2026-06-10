# Path: app/models/client_log.py
# File: client_log.py
# Created: 2026-06-10
# Purpose: ClientLog ORM model - structured frontend telemetry / log feed (DWB-371)
# Caller: app/services/client_log.py, app/routers/client_logs.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: ClientLog, ClientLogLevel
# Last Modified: 2026-06-10

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ClientLogLevel(str, enum.Enum):
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"


class ClientLog(Base):
    """Frontend (or generally client-side) structured log record.

    Kept separate from error_logs because error_logs is shaped for backend
    exception capture (stack_trace, file_path, line_number, status_code,
    endpoint) and would have most of its columns null for every client
    record. client_logs is leaner and carries the things a UI actually
    produces: level, category, route, free-form JSON context.

    Retention: bounded at insert-time. See client_log.trim_to_cap.
    """

    __tablename__ = "client_logs"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="frontend", server_default="frontend"
    )
    level: Mapped[ClientLogLevel] = mapped_column(
        Enum(ClientLogLevel), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    route: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )
