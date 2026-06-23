# Path: app/schemas/score.py
# File: score.py
# Created: 2026-06-22
# Purpose: Pydantic schemas for the agent scoring API (DWB-424 read; DWB-426 human write) - leaderboard rows, ledger entries, per-agent detail, human award request/response.
# Caller: app/routers/scores.py
# Callees: pydantic
# Data In: service dicts from app.services.scoring, human award request body
# Data Out: LeaderboardRow, ScoreLedgerEntry, AgentScoreDetail, HumanScoreRequest/Response
# Last Modified: 2026-06-23 (DWB-427)

from pydantic import BaseModel


class LeaderboardRow(BaseModel):
    agent_id: int
    agent_name: str | None
    agent_role: str | None
    reputation: int
    sprint_delta: int
    influence: int


class ScoreLedgerEntry(BaseModel):
    id: int
    delta: int
    source: str
    trigger_type: str
    reason: str | None
    actor_agent_id: int | None
    actor_name: str | None
    actor_cost: int
    ref_type: str | None
    ref_id: int | None
    reverted_by: int | None
    sprint_id: int | None
    created_at: str | None


class AgentScoreDetail(BaseModel):
    agent_id: int
    project_id: int
    reputation: int
    influence: int
    sprint_delta: int
    ledger: list[ScoreLedgerEntry]


class HumanScoreRequest(BaseModel):
    """Human carrot/stick (DWB-426). `agent` is a name or id; delta is signed
    (>0 carrot, <0 stick); reason optional."""
    agent: str
    delta: int
    reason: str | None = None


class HumanScoreResponse(BaseModel):
    status: str
    event_id: int
    subject_agent_id: int
    subject_name: str | None
    delta: int
    trigger_type: str
    reputation: int
    sprint_delta: int
    broadcast_count: int


class PeerScoreRequest(BaseModel):
    """Peer carrot/stick (DWB-427). The actor is the X-Agent-ID caller; `subject`
    is a name or id; delta is signed (>0 grant, <0 demerit); reason optional."""
    subject: str
    delta: int
    reason: str | None = None


class PeerScoreResponse(BaseModel):
    status: str
    event_id: int
    actor_agent_id: int
    subject_agent_id: int
    subject_name: str | None
    delta: int
    trigger_type: str
    subject_reputation: int
    actor_influence_remaining: int
    broadcast_count: int
