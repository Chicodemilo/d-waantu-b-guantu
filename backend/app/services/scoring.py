# Path: app/services/scoring.py
# File: scoring.py
# Created: 2026-06-22
# Purpose: Agent scoring service (DWB-424) - apply/revert ledger events, rebuild the derived agent_score cache from the authoritative score_event ledger, and read-side leaderboard / per-agent ledger queries.
# Caller: app/routers/scores.py, app/services/* (auto-triggers, DWB-425)
# Callees: app/models/score_event.py, app/models/agent_score.py, app/models/sprint.py, app/models/agent.py, app/models/project_agent.py, app/config/scoring.py
# Data In: db: Session, score event fields
# Data Out: ScoreEvent, AgentScore, leaderboard / ledger dicts
# Last Modified: 2026-06-22

"""Agent scoring (DWB-424).

The score_event ledger is the source of truth; agent_score is a derived cache.
``apply_score_event`` inserts one immutable ledger row and updates the cache in
the same transaction. ``rebuild_agent_scores`` recomputes the cache from the
ledger so the cache can always be regenerated. Corrections never mutate or
delete a row: ``revert_score_event`` appends a reverting row (delta = -original)
and stamps the original's ``reverted_by``.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.scoring import INITIAL_INFLUENCE
from app.models.agent import Agent
from app.models.agent_score import AgentScore
from app.models.project_agent import ProjectAgent
from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.models.sprint import Sprint, SprintStatus


# ---------------------------------------------------------------------------
# Cache mutation
# ---------------------------------------------------------------------------


def _get_or_create_score(db: Session, agent_id: int, project_id: int) -> AgentScore:
    """Fetch the agent_score cache row, creating it (with the starting
    influence budget) on first touch."""
    row = db.get(AgentScore, (agent_id, project_id))
    if row is None:
        row = AgentScore(
            agent_id=agent_id,
            project_id=project_id,
            reputation=0,
            influence=INITIAL_INFLUENCE,
        )
        db.add(row)
        db.flush()
    return row


def _bump_cache(
    db: Session,
    agent_id: int,
    project_id: int,
    *,
    reputation_delta: int = 0,
    influence_delta: int = 0,
) -> None:
    row = _get_or_create_score(db, agent_id, project_id)
    row.reputation += reputation_delta
    row.influence += influence_delta
    db.flush()


# ---------------------------------------------------------------------------
# Apply / revert
# ---------------------------------------------------------------------------


def apply_score_event(
    db: Session,
    *,
    project_id: int,
    subject_agent_id: int,
    trigger_type: ScoreTriggerType,
    delta: int,
    source: ScoreSource,
    sprint_id: int | None = None,
    actor_agent_id: int | None = None,
    actor_cost: int = 0,
    reason: str | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    commit: bool = True,
) -> ScoreEvent:
    """Insert one score_event AND update the agent_score cache in one
    transaction.

    The subject's reputation moves by ``delta``. When an actor is given and
    spent influence (``actor_cost`` > 0), the actor's influence is debited too
    (peer economy, fully exercised in DWB-427). Pass ``commit=False`` to fold
    this into a caller-owned transaction (e.g. the auto-trigger engine running
    inside a request that also closes a ticket).
    """
    event = ScoreEvent(
        project_id=project_id,
        sprint_id=sprint_id,
        subject_agent_id=subject_agent_id,
        delta=delta,
        source=source,
        trigger_type=trigger_type,
        actor_agent_id=actor_agent_id,
        actor_cost=actor_cost,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    db.add(event)
    db.flush()

    _bump_cache(db, subject_agent_id, project_id, reputation_delta=delta)
    if actor_agent_id is not None and actor_cost:
        _bump_cache(db, actor_agent_id, project_id, influence_delta=-actor_cost)

    if commit:
        db.commit()
        db.refresh(event)
    return event


def event_exists_for_ref(
    db: Session,
    *,
    project_id: int,
    subject_agent_id: int,
    trigger_type: ScoreTriggerType,
    ref_type: str,
    ref_id: int,
) -> bool:
    """Idempotency guard for the auto-trigger engine (DWB-425): True when a
    non-reverted score_event already exists for this (subject, trigger, ref).
    Lets callers avoid double-awarding the same ticket / failure."""
    existing = db.scalar(
        select(ScoreEvent.id)
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.subject_agent_id == subject_agent_id)
        .where(ScoreEvent.trigger_type == trigger_type)
        .where(ScoreEvent.ref_type == ref_type)
        .where(ScoreEvent.ref_id == ref_id)
        .limit(1)
    )
    return existing is not None


def revert_score_event(
    db: Session,
    event_id: int,
    *,
    actor_agent_id: int | None = None,
    reason: str | None = None,
    commit: bool = True,
) -> ScoreEvent | None:
    """Append a reverting row that nets out a prior event and stamp the
    original's ``reverted_by``. Returns the new reverting event, or None if the
    original does not exist or is already reverted.

    Because reputation = sum(all deltas), the appended -delta row neutralizes
    the original automatically; no special rebuild handling is needed.
    """
    original = db.get(ScoreEvent, event_id)
    if original is None or original.reverted_by is not None:
        return None

    revert = apply_score_event(
        db,
        project_id=original.project_id,
        subject_agent_id=original.subject_agent_id,
        trigger_type=original.trigger_type,
        delta=-original.delta,
        source=original.source,
        sprint_id=original.sprint_id,
        actor_agent_id=actor_agent_id,
        actor_cost=0,
        reason=reason or f"revert of score_event {event_id}",
        ref_type="score_event",
        ref_id=event_id,
        commit=False,
    )
    original.reverted_by = revert.id
    db.flush()

    if commit:
        db.commit()
        db.refresh(revert)
    return revert


def rebuild_agent_scores(db: Session, project_id: int) -> int:
    """Recompute every agent_score row for a project from the ledger.

    reputation = sum(delta) over events where the agent is the subject.
    influence  = INITIAL_INFLUENCE - sum(actor_cost) the agent has spent.
    (The per-sprint influence reset is DWB-427; today this is the all-time
    spend, which is 0 until the peer economy lands.)

    Returns the number of agent_score rows touched. The ledger is authoritative,
    so this is the recovery path if the cache ever drifts.
    """
    rep_rows = db.execute(
        select(
            ScoreEvent.subject_agent_id,
            func.coalesce(func.sum(ScoreEvent.delta), 0),
        )
        .where(ScoreEvent.project_id == project_id)
        .group_by(ScoreEvent.subject_agent_id)
    ).all()
    cost_rows = db.execute(
        select(
            ScoreEvent.actor_agent_id,
            func.coalesce(func.sum(ScoreEvent.actor_cost), 0),
        )
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.actor_agent_id.isnot(None))
        .group_by(ScoreEvent.actor_agent_id)
    ).all()

    rep = {aid: int(total) for aid, total in rep_rows}
    cost = {aid: int(total) for aid, total in cost_rows}
    agent_ids = set(rep) | set(cost)

    for aid in agent_ids:
        row = _get_or_create_score(db, aid, project_id)
        row.reputation = rep.get(aid, 0)
        row.influence = INITIAL_INFLUENCE - cost.get(aid, 0)

    db.commit()
    return len(agent_ids)


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------


def active_sprint_id(db: Session, project_id: int) -> int | None:
    """The project's single active sprint id, or None."""
    return db.scalar(
        select(Sprint.id)
        .where(Sprint.project_id == project_id)
        .where(Sprint.status == SprintStatus.active)
    )


def _sprint_delta_map(
    db: Session, project_id: int, sprint_id: int | None
) -> dict[int, int]:
    """Per-subject sum of deltas within a sprint. Empty when no active sprint."""
    if sprint_id is None:
        return {}
    rows = db.execute(
        select(
            ScoreEvent.subject_agent_id,
            func.coalesce(func.sum(ScoreEvent.delta), 0),
        )
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.sprint_id == sprint_id)
        .group_by(ScoreEvent.subject_agent_id)
    ).all()
    return {aid: int(total) for aid, total in rows}


def get_leaderboard(db: Session, project_id: int) -> list[dict]:
    """Per-agent standings for a project, sorted as a leaderboard.

    Each row carries all-time reputation, this-sprint delta (sum of deltas in
    the active sprint), and remaining influence. Covers the full project roster
    (project_agents); agents with no events show reputation 0 / influence
    INITIAL_INFLUENCE so the Team Status section can render everyone.
    """
    sprint_id = active_sprint_id(db, project_id)
    delta_map = _sprint_delta_map(db, project_id, sprint_id)

    score_rows = db.execute(
        select(AgentScore.agent_id, AgentScore.reputation, AgentScore.influence)
        .where(AgentScore.project_id == project_id)
    ).all()
    scores = {aid: (rep, infl) for aid, rep, infl in score_rows}

    roster = db.execute(
        select(Agent.id, Agent.name, Agent.role)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
    ).all()

    out: list[dict] = []
    for agent_id, name, role in roster:
        rep, infl = scores.get(agent_id, (0, INITIAL_INFLUENCE))
        out.append({
            "agent_id": agent_id,
            "agent_name": name,
            "agent_role": role,
            "reputation": rep,
            "sprint_delta": delta_map.get(agent_id, 0),
            "influence": infl,
        })

    out.sort(key=lambda r: (-r["reputation"], -r["sprint_delta"], r["agent_name"] or ""))
    return out


def get_agent_summary(db: Session, agent_id: int, project_id: int) -> dict:
    """Summary score figures for one agent on one project."""
    row = db.get(AgentScore, (agent_id, project_id))
    sprint_id = active_sprint_id(db, project_id)
    delta_map = _sprint_delta_map(db, project_id, sprint_id)
    return {
        "agent_id": agent_id,
        "project_id": project_id,
        "reputation": row.reputation if row else 0,
        "influence": row.influence if row else INITIAL_INFLUENCE,
        "sprint_delta": delta_map.get(agent_id, 0),
    }


def get_agent_ledger(
    db: Session, agent_id: int, project_id: int, limit: int = 100
) -> list[dict]:
    """The reasoned event history for one agent on one project (newest first),
    with the actor's name resolved for peer events (AgentPage view)."""
    actor = Agent.__table__.alias("actor")
    rows = db.execute(
        select(
            ScoreEvent.id,
            ScoreEvent.delta,
            ScoreEvent.source,
            ScoreEvent.trigger_type,
            ScoreEvent.reason,
            ScoreEvent.actor_agent_id,
            actor.c.name.label("actor_name"),
            ScoreEvent.actor_cost,
            ScoreEvent.ref_type,
            ScoreEvent.ref_id,
            ScoreEvent.reverted_by,
            ScoreEvent.sprint_id,
            ScoreEvent.created_at,
        )
        .outerjoin(actor, ScoreEvent.actor_agent_id == actor.c.id)
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.subject_agent_id == agent_id)
        .order_by(ScoreEvent.created_at.desc(), ScoreEvent.id.desc())
        .limit(limit)
    ).all()

    out: list[dict] = []
    for r in rows:
        out.append({
            "id": r.id,
            "delta": r.delta,
            "source": r.source.value if hasattr(r.source, "value") else r.source,
            "trigger_type": (
                r.trigger_type.value
                if hasattr(r.trigger_type, "value")
                else r.trigger_type
            ),
            "reason": r.reason,
            "actor_agent_id": r.actor_agent_id,
            "actor_name": r.actor_name,
            "actor_cost": r.actor_cost,
            "ref_type": r.ref_type,
            "ref_id": r.ref_id,
            "reverted_by": r.reverted_by,
            "sprint_id": r.sprint_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return out
