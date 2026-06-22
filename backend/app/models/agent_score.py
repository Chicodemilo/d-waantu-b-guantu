# Path: app/models/agent_score.py
# File: agent_score.py
# Created: 2026-06-22
# Purpose: AgentScore ORM model (DWB-424) - derived per-(agent, project) score cache. Rebuildable from the score_event ledger, which is authoritative.
# Caller: app/services/scoring.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: AgentScore
# Last Modified: 2026-06-22

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column


from app.database import Base


class AgentScore(Base):
    """Derived score cache for one agent on one project.

    Scores are per-(agent, project) because agents are global identities. This
    table is a CACHE: `reputation` is the sum of all score_event.delta to the
    agent, recomputable via scoring.rebuild_agent_scores. `influence` is the
    spendable per-sprint peer budget (DWB-427 adds the per-sprint reset).
    """

    __tablename__ = "agent_score"

    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), primary_key=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), primary_key=True
    )
    reputation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    influence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
