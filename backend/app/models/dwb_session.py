# Path: app/models/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: DwbSession ORM model - passive user-bounded session for time + token rollup (DWB-335, DWB-346 headline, DWB-381 slash escape hatch, DWB-382 ai_classifier fallback [retired DWB-402, enum kept as tombstone])
# Caller: app/services/dwb_session.py (DWB-337), app/routers/dwb_sessions.py (DWB-338)
# Callees: app/database.Base
# Data In: DB rows
# Data Out: DwbSession, DwbOpenMethod, DwbCloseMethod, DwbCloseReason
# Last Modified: 2026-06-11

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DwbOpenMethod(str, enum.Enum):
    regex = "regex"
    ai_confident = "ai_confident"
    ai_asked = "ai_asked"
    # DWB-381: deterministic slash-command escape hatch. Stamped when the
    # user types /dwb-open and the slash command curls /api/sessions/open
    # with open_method=slash. Independent of the regex + AI layers so the
    # user always has a guaranteed open path regardless of phrase matching.
    slash = "slash"
    # DWB-382 / DWB-402: async Haiku classifier fallback. RETIRED in DWB-402;
    # no new sessions are stamped with this method. Kept as a legacy tombstone
    # so historical rows (open_method=ai_classifier) still load. Was an
    # AI-method (open_phrase nulled before persist, per DWB-351).
    ai_classifier = "ai_classifier"


class DwbCloseMethod(str, enum.Enum):
    regex = "regex"
    ai_confident = "ai_confident"
    ai_asked = "ai_asked"
    idle_timeout = "idle_timeout"
    # DWB-381: deterministic slash-command escape hatch. Stamped when the
    # user types /dwb-close and the slash command curls
    # /api/sessions/{id}/close with close_method=slash. Mirrors the open
    # side of the escape hatch above.
    slash = "slash"
    # DWB-382 / DWB-402: async Haiku classifier fallback. RETIRED in DWB-402;
    # no new sessions are stamped with this method. Kept as a legacy tombstone
    # so historical rows still load. Was an AI-method (close_phrase nulled
    # before persist, per DWB-351).
    ai_classifier = "ai_classifier"


class DwbCloseReason(str, enum.Enum):
    explicit = "explicit"
    idle = "idle"
    manual = "manual"


class DwbSession(Base):
    """A DWB session — a user-bounded span (open phrase -> close phrase / idle)
    that aggregates one or more Claude Code hook_sessions for passive time +
    token rollup.

    Single-active invariant: at most one row per project_id with closed_at IS
    NULL. Enforced by a STORED generated column (`is_open` = 1 when closed_at
    IS NULL else NULL) plus a composite UNIQUE index on (project_id, is_open).
    MySQL treats NULL as distinct in UNIQUE, so closed rows never collide.
    """

    __tablename__ = "dwb_sessions"
    __table_args__ = (
        Index(
            "uq_dwb_sessions_one_open_per_project",
            "project_id",
            "is_open",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )

    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    open_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)

    open_method: Mapped[DwbOpenMethod] = mapped_column(
        Enum(DwbOpenMethod), nullable=False
    )
    close_method: Mapped[DwbCloseMethod | None] = mapped_column(
        Enum(DwbCloseMethod), nullable=True
    )
    close_reason: Mapped[DwbCloseReason | None] = mapped_column(
        Enum(DwbCloseReason), nullable=True
    )

    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_time_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # DWB-346: short user-facing summary of what the session was about. Set
    # optionally on close via POST /api/sessions/{id}/close. 80-char cap so
    # the dashboard list row stays one line; longer text is the detail view's
    # job, not the headline's.
    headline: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Generated single-active marker: 1 when closed_at IS NULL, NULL when
    # closed_at IS NOT NULL. The (project_id, is_open) UNIQUE index above
    # uses this to enforce one-open-per-project. Generated STORED so the
    # UNIQUE index has a concrete value to compare against on MySQL.
    is_open: Mapped[int | None] = mapped_column(
        SmallInteger,
        Computed(
            "(CASE WHEN closed_at IS NULL THEN 1 ELSE NULL END)",
            persisted=True,
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
