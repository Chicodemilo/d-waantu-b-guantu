# Path: app/models/entity_keyword.py
# File: entity_keyword.py
# Created: 2026-06-25
# Purpose: EntityKeyword ORM model (DWB-481) - a GENERIC weighted keyword row.
#          One row per (entity, keyword): `weight` is the per-entity occurrence
#          count produced by the deterministic extractor (DWB-482). Populated
#          for entity_type='dwb_session' this sprint (keywords mined from a
#          session's activity corpus); `entity_type` is the seam that lets the
#          same table extend to tickets/epics/agents later without a schema change.
# Caller: app/services/* (keyword extraction/synthesis, DWB-482..483)
# Callees: app/database.Base
# Data In: DB rows
# Data Out: EntityKeyword
# Last Modified: 2026-06-25

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EntityKeyword(Base):
    """A single weighted keyword attached to an arbitrary entity.

    Generic by design (DWB-481): `entity_type` + `entity_id` form a polymorphic
    pointer rather than a hard FK, so the table is not bound to dwb_sessions.
    This sprint only `entity_type='dwb_session'` rows are written, but ticket /
    epic / agent keyword sets can land later with no migration.

    `weight` is an integer ranking weight (higher = more prominent). Its exact
    meaning depends on the writer: a pure-TF caller stores the raw occurrence
    count, while the dwb_session close path stores a TF-IDF RELEVANCE SCORE
    (DWB-500) so terms common across many sessions sink and session-distinctive
    terms rise. Either way it is an int >= 1 and consumers sort by it desc.
    `source` is a free-form label for where the term was mined from.

    Indexes (DWB-481): a single-column index on `keyword` for term lookups
    across entities, and a composite index on (entity_type, entity_id) so all
    keywords for one entity load with one indexed scan.
    """

    __tablename__ = "entity_keywords"
    __table_args__ = (
        Index("ix_entity_keywords_keyword", "keyword"),
        Index("ix_entity_keywords_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    # Int ranking weight (>=1): raw TF count for pure-TF callers, TF-IDF
    # relevance score for the dwb_session close path (DWB-500).
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Free-form label for the mining source (e.g. 'extraction').
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
