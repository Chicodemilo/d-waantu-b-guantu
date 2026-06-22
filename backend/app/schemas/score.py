# Path: app/schemas/score.py
# File: score.py
# Created: 2026-06-22
# Purpose: Pydantic schemas for the agent scoring read API (DWB-424) - leaderboard rows, ledger entries, per-agent detail.
# Caller: app/routers/scores.py
# Callees: pydantic
# Data In: service dicts from app.services.scoring
# Data Out: LeaderboardRow, ScoreLedgerEntry, AgentScoreDetail
# Last Modified: 2026-06-22

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
