# Path: app/models/failed_hook.py
# File: failed_hook.py
# Created: 2026-06-03
# Purpose: FailedHook ORM model — record of hook endpoint failures (parse / DB / handler)
# Caller: app/services/failed_hook.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: FailedHook
# Last Modified: 2026-06-03

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FailedHook(Base):
    __tablename__ = "failed_hooks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    hook_event: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False)
