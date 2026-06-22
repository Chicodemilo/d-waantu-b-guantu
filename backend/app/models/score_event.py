# Path: app/models/score_event.py
# File: score_event.py
# Created: 2026-06-22
# Purpose: ScoreEvent ORM model (DWB-424) - the append-only agent-scoring ledger. Source of truth; agent_score is a derived cache rebuilt from these rows.
# Caller: app/services/scoring.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: ScoreEvent, ScoreSource, ScoreTriggerType
# Last Modified: 2026-06-22

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScoreSource(str, enum.Enum):
    """Who initiated a score event."""
    auto = "auto"
    human = "human"
    peer = "peer"


class ScoreTriggerType(str, enum.Enum):
    """The specific reason class for a score event.

    auto triggers (DWB-425): ticket_closed, rework, test_failure, stale,
    zero_token_close, gate_miss, forgot.
    human tools (DWB-426): carrot, stick.
    peer economy (DWB-427): peer_grant, peer_demerit.
    """
    ticket_closed = "ticket_closed"
    rework = "rework"
    test_failure = "test_failure"
    stale = "stale"
    zero_token_close = "zero_token_close"
    gate_miss = "gate_miss"
    forgot = "forgot"
    carrot = "carrot"
    stick = "stick"
    peer_grant = "peer_grant"
    peer_demerit = "peer_demerit"


class ScoreEvent(Base):
    """One immutable point change applied to an agent's reputation.

    Append-only: corrections never mutate or delete a row, they append a
    reverting row (delta = -original) and stamp the original's ``reverted_by``.
    The whole history stays auditable and reversible (DWB-424 core principle).
    """

    __tablename__ = "score_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    sprint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sprints.id"), nullable=True, index=True
    )
    subject_agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[ScoreSource] = mapped_column(Enum(ScoreSource), nullable=False)
    trigger_type: Mapped[ScoreTriggerType] = mapped_column(
        Enum(ScoreTriggerType), nullable=False
    )
    # Peer who awarded it (null for auto/human). The influence they spent is
    # actor_cost (peer economy, DWB-427).
    actor_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=True
    )
    actor_cost: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Optional: auto-triggers self-describe with a reason; human/peer paths
    # (wave 2) may omit it (frontend renders null as "-").
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Link to the triggering entity (ticket / failure_record / tool_action).
    ref_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Corrections point back to the event they reverse; rows are never deleted.
    reverted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("score_event.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
