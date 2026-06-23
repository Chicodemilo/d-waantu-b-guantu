# Path: app/services/scoring.py
# File: scoring.py
# Created: 2026-06-22
# Purpose: Agent scoring service (DWB-424 ledger/cache/read; DWB-426 human awards + team broadcast via alerts) - apply/revert ledger events, rebuild the derived agent_score cache, leaderboard / per-agent ledger queries, agent-ref resolution, and carrot/stick broadcast.
# Caller: app/routers/scores.py, app/services/* (auto-triggers, DWB-425)
# Callees: app/models/score_event.py, app/models/agent_score.py, app/models/alert.py, app/models/sprint.py, app/models/agent.py, app/models/project_agent.py, app/config/scoring.py
# Data In: db: Session, score event fields
# Data Out: ScoreEvent, AgentScore, Alert (broadcast), leaderboard / ledger dicts
# Last Modified: 2026-06-23 (DWB-442: human-carrot peer alerts become a pile-on CTA)

"""Agent scoring (DWB-424).

The score_event ledger is the source of truth; agent_score is a derived cache.
``apply_score_event`` inserts one immutable ledger row and updates the cache in
the same transaction. ``rebuild_agent_scores`` recomputes the cache from the
ledger so the cache can always be regenerated. Corrections never mutate or
delete a row: ``revert_score_event`` appends a reverting row (delta = -original)
and stamps the original's ``reverted_by``.
"""

import logging
import math

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.scoring import (
    INITIAL_INFLUENCE,
    MAX_DING_PER_ACTION,
    MAX_DING_PER_TARGET_PER_SPRINT,
    MAX_GRANT_PER_TARGET_PER_SPRINT,
)
from app.models.agent import Agent
from app.models.agent_score import AgentScore
from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.project_agent import ProjectAgent
from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.models.sprint import Sprint, SprintStatus
from app.services.activity_log import log_activity

logger = logging.getLogger(__name__)

# Max chars of a reason persisted into an activity-feed score event (DWB-432).
_SCORE_REASON_MAX = 100


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


def _leader_agent_id(db: Session, project_id: int) -> int | None:
    """The project's current #1 agent (top reputation among the roster, name
    tiebreak), or None when there is no meaningful leader (all reputations <= 0,
    e.g. an all-zero board). Used to detect lead changes (DWB-432)."""
    row = db.execute(
        select(Agent.id, AgentScore.reputation, Agent.name)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .join(
            AgentScore,
            (AgentScore.agent_id == Agent.id)
            & (AgentScore.project_id == project_id),
        )
        .where(ProjectAgent.project_id == project_id)
        .order_by(AgentScore.reputation.desc(), Agent.name.asc())
        .limit(1)
    ).first()
    if row is None:
        return None
    agent_id, reputation, _name = row
    return agent_id if reputation > 0 else None


def _emit_lead_change(db: Session, project_id: int, before: int | None) -> None:
    """If the project #1 changed from ``before``, emit a lead_change feed event.
    Guarded so it can never break the score write. Flushes only; the caller's
    commit persists it alongside the score row."""
    try:
        after = _leader_agent_id(db, project_id)
        if after is None or after == before:
            return
        new_name = db.get(Agent, after).name if after else None
        prev_name = db.get(Agent, before).name if before else None
        log_activity(
            db, project_id, None, "agent", after, "lead_change",
            {"new_leader": new_name, "previous_leader": prev_name},
        )
        logger.info(
            "lead_change project=%s %s -> %s", project_id, prev_name, new_name
        )
    except Exception:
        logger.warning("lead_change emit failed for project %s", project_id, exc_info=True)


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

    DWB-432: emits a lead_change feed event (any source) when this write flips
    the project #1 spot.
    """
    # Capture the leader BEFORE the write so we can detect a #1 flip.
    leader_before = _leader_agent_id(db, project_id)

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

    _emit_lead_change(db, project_id, leader_before)

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
    influence  = INITIAL_INFLUENCE - actor_cost spent in the ACTIVE sprint
    (DWB-427: per-sprint, so it auto-resets; ledger-derived, never a drifting
    stored counter).

    Returns the number of agent_score rows touched. The ledger is authoritative,
    so this is the recovery path if the cache ever drifts.

    Reconciles the FULL set of agents = ledger-event subjects/actors UNION
    existing agent_score rows UNION the project roster. Including existing cache
    rows is essential: an agent whose events were all removed (e.g. a ticket
    delete cascaded its score_events) must reset to 0 / INITIAL_INFLUENCE rather
    than keep a stale cached value (DWB-427 follow-up).
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
    agent_ids = set(rep) | {aid for aid, _ in cost_rows}

    # Influence is per-sprint: remaining = INITIAL_INFLUENCE - actor_cost spent
    # in the ACTIVE sprint (so it auto-resets each sprint). Ledger-derived, never
    # a drifting stored counter.
    sprint_spent = _influence_spent_map(db, project_id, active_sprint_id(db, project_id))
    agent_ids |= set(sprint_spent)

    # Include agents that already have a cache row (so drained agents reset) and
    # the project roster (so the cache is complete for the leaderboard).
    agent_ids |= set(db.scalars(
        select(AgentScore.agent_id).where(AgentScore.project_id == project_id)
    ).all())
    agent_ids |= set(db.scalars(
        select(ProjectAgent.agent_id).where(ProjectAgent.project_id == project_id)
    ).all())

    for aid in agent_ids:
        row = _get_or_create_score(db, aid, project_id)
        row.reputation = rep.get(aid, 0)
        row.influence = INITIAL_INFLUENCE - sprint_spent.get(aid, 0)

    db.commit()
    logger.info(
        "rebuilt %d agent_score rows for project %s from the ledger",
        len(agent_ids), project_id,
    )
    return len(agent_ids)


def _influence_spent_map(
    db: Session, project_id: int, sprint_id: int | None
) -> dict[int, int]:
    """Per-actor sum of actor_cost spent within a sprint. Empty when no sprint.
    The basis for ledger-derived, per-sprint influence (DWB-427)."""
    if sprint_id is None:
        return {}
    rows = db.execute(
        select(
            ScoreEvent.actor_agent_id,
            func.coalesce(func.sum(ScoreEvent.actor_cost), 0),
        )
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.sprint_id == sprint_id)
        .where(ScoreEvent.actor_agent_id.isnot(None))
        .group_by(ScoreEvent.actor_agent_id)
    ).all()
    return {aid: int(total) for aid, total in rows}


def remaining_influence(
    db: Session, agent_id: int, project_id: int, sprint_id: int | None = None
) -> int:
    """An agent's spendable influence this sprint, derived from the ledger:
    INITIAL_INFLUENCE - actor_cost spent in the (active) sprint."""
    if sprint_id is None:
        sprint_id = active_sprint_id(db, project_id)
    spent = _influence_spent_map(db, project_id, sprint_id).get(agent_id, 0)
    return INITIAL_INFLUENCE - spent


def peer_target_totals(
    db: Session, project_id: int, sprint_id: int | None, actor_id: int, subject_id: int
) -> tuple[int, int]:
    """(granted, dinged) reputation magnitudes already applied by actor->subject
    as PEER events in a sprint. Basis for the per-target-per-sprint caps."""
    if sprint_id is None:
        return (0, 0)
    rows = db.execute(
        select(ScoreEvent.delta)
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.sprint_id == sprint_id)
        .where(ScoreEvent.source == ScoreSource.peer)
        .where(ScoreEvent.actor_agent_id == actor_id)
        .where(ScoreEvent.subject_agent_id == subject_id)
    ).all()
    granted = sum(d for (d,) in rows if d > 0)
    dinged = sum(-d for (d,) in rows if d < 0)
    return (granted, dinged)


def peer_score(
    db: Session,
    *,
    project_id: int,
    actor: Agent,
    subject: Agent,
    delta: int,
    reason: str | None = None,
) -> tuple[ScoreEvent, int]:
    """Apply a peer carrot/stick (DWB-427). The actor spends abs(delta)
    influence; the subject's reputation moves by delta. Enforces the anti-gaming
    rules, raising HTTPException(400) on any violation BEFORE writing anything:

      - no self-scoring
      - actor influence (this sprint, ledger-derived) >= cost
      - per-action ding cap (MAX_DING_PER_ACTION)
      - per-target-per-sprint ding AND grant caps

    Broadcasts at normal severity on success. Returns (event, broadcast_count).
    """
    def _reject(msg: str):
        logger.warning(
            "peer score rejected: %s (actor=%s subject=%s delta=%+d project=%s)",
            msg, actor.name, subject.name, delta, project_id,
        )
        return HTTPException(400, msg)

    if delta == 0:
        raise _reject("delta must be non-zero (positive grant / negative demerit)")
    if actor.id == subject.id:
        raise _reject("no self-scoring: an agent cannot score itself")

    sid = active_sprint_id(db, project_id)
    cost = abs(delta)

    remaining = remaining_influence(db, actor.id, project_id, sid)
    if cost > remaining:
        raise _reject(
            f"insufficient influence: this action costs {cost} but {actor.name} "
            f"has {remaining} of {INITIAL_INFLUENCE} left this sprint"
        )

    granted, dinged = peer_target_totals(db, project_id, sid, actor.id, subject.id)
    if delta < 0:
        if cost > MAX_DING_PER_ACTION:
            raise _reject(
                f"per-action ding cap is {MAX_DING_PER_ACTION}; requested {cost}"
            )
        if dinged + cost > MAX_DING_PER_TARGET_PER_SPRINT:
            raise _reject(
                f"per-target ding cap this sprint is {MAX_DING_PER_TARGET_PER_SPRINT} "
                f"({actor.name} has already docked {subject.name} by {dinged})"
            )
        trigger = ScoreTriggerType.peer_demerit
    else:
        if granted + cost > MAX_GRANT_PER_TARGET_PER_SPRINT:
            raise _reject(
                f"per-target grant cap this sprint is {MAX_GRANT_PER_TARGET_PER_SPRINT} "
                f"({actor.name} has already granted {subject.name} {granted})"
            )
        trigger = ScoreTriggerType.peer_grant

    event = apply_score_event(
        db, project_id=project_id, subject_agent_id=subject.id, sprint_id=sid,
        trigger_type=trigger, delta=delta, source=ScoreSource.peer,
        actor_agent_id=actor.id, actor_cost=cost, reason=reason, commit=False,
    )
    count = broadcast_score_change(
        db, project_id=project_id, subject_agent_id=subject.id,
        subject_name=subject.name, delta=delta, reason=reason, source="peer",
        actor_agent_id=actor.id, actor_name=actor.name,
    )
    db.commit()
    db.refresh(event)
    logger.info(
        "peer %s: %s %+d to %s (project %s)",
        trigger.value, actor.name, delta, subject.name, project_id,
    )
    _emit_score_feed_event(
        db, project_id=project_id, actor_agent_id=actor.id,
        subject_name=subject.name, subject_agent_id=subject.id,
        delta=delta, reason=reason, source="peer",
    )
    return event, count


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
    # Influence is ledger-derived per active sprint (DWB-427), not the cache.
    spent_map = _influence_spent_map(db, project_id, sprint_id)

    rep_rows = db.execute(
        select(AgentScore.agent_id, AgentScore.reputation)
        .where(AgentScore.project_id == project_id)
    ).all()
    rep_map = {aid: rep for aid, rep in rep_rows}

    # DWB-432: agents with at least one subject score event (for the tier; an
    # unscored agent gets the 'unscored' tier even when ranked last).
    scored_ids = set(db.scalars(
        select(ScoreEvent.subject_agent_id)
        .where(ScoreEvent.project_id == project_id)
        .distinct()
    ).all())

    roster = db.execute(
        select(Agent.id, Agent.name, Agent.role)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
    ).all()

    out: list[dict] = []
    for agent_id, name, role in roster:
        out.append({
            "agent_id": agent_id,
            "agent_name": name,
            "agent_role": role,
            "reputation": rep_map.get(agent_id, 0),
            "sprint_delta": delta_map.get(agent_id, 0),
            "influence": INITIAL_INFLUENCE - spent_map.get(agent_id, 0),
        })

    out.sort(key=lambda r: (-r["reputation"], -r["sprint_delta"], r["agent_name"] or ""))
    # DWB-432: 1-based rank + tier (reuse the get_standing tiering).
    total = len(out)
    for i, row in enumerate(out, start=1):
        row["rank"] = i
        row["tier"] = _standing_tier(i, total, row["agent_id"] in scored_ids)
    return out


def is_project_member(db: Session, agent_id: int, project_id: int) -> bool:
    """True when the agent is on the project roster (project_agents). The
    scoring WRITE paths (DWB-430) use this so a score can only be recorded
    against an agent who actually belongs to the project, even though
    resolve_agent_ref looks agents up globally by name/id."""
    return db.scalar(
        select(ProjectAgent.agent_id)
        .where(ProjectAgent.project_id == project_id)
        .where(ProjectAgent.agent_id == agent_id)
        .limit(1)
    ) is not None


def resolve_agent_ref(db: Session, ref: str | int) -> Agent | None:
    """Resolve an agent by database id (all-digit ref) or by name
    (case-insensitive). Agent names are globally unique, so a name match is
    unambiguous. Used by the human scoring tools (DWB-426) where the slash
    command passes a name like "archie_dwb"."""
    s = str(ref).strip()
    if not s:
        return None
    agent = None
    if s.isdigit():
        agent = db.get(Agent, int(s))
    if agent is None:
        agent = db.scalar(select(Agent).where(Agent.name.ilike(s)))
    return agent


# ---------------------------------------------------------------------------
# Broadcast (DWB-426 human, DWB-427 peer)
# ---------------------------------------------------------------------------


def broadcast_score_change(
    db: Session,
    *,
    project_id: int,
    subject_agent_id: int,
    subject_name: str | None,
    delta: int,
    reason: str | None,
    source: str,
    actor_agent_id: int | None = None,
    actor_name: str | None = None,
) -> int:
    """Notify every project agent (plus the subject) of a carrot/stick via the
    alerts system. Human events use elevated (critical) severity; peer events
    use normal (info). The subject's own row is phrased directly ("You
    received ..."); everyone else sees the third-person form. Auto-triggers do
    NOT call this (mechanical/too frequent). Returns the number of alert rows
    written. The caller owns the commit.
    """
    severity = AlertSeverity.critical if source == "human" else AlertSeverity.info
    origin = "the human" if source == "human" else (actor_name or "a peer")
    sign = f"{delta:+d}"
    suffix = f": {reason}" if reason else ""
    name = subject_name or f"agent {subject_agent_id}"

    # raised_by_agent_id is NOT NULL: use the actor for a peer event; for a human
    # event there is no actor agent, so anchor it on the subject.
    raised_by = actor_agent_id if (source == "peer" and actor_agent_id) else subject_agent_id

    recipient_ids = set(db.scalars(
        select(ProjectAgent.agent_id).where(ProjectAgent.project_id == project_id)
    ).all())
    recipient_ids.add(subject_agent_id)

    # DWB-442: a human CARROT (source=human, delta>0) turns the non-subject
    # (peer) alert into a pile-on call-to-action carrying the reason. Human
    # sticks (delta<0) and all peer-sourced events stay notify-only, and the
    # subject's own "You received ..." row is never a CTA.
    human_carrot = source == "human" and delta > 0
    cta_reason = f" for {reason}" if reason else ""

    count = 0
    for aid in recipient_ids:
        if aid == subject_agent_id:
            title = f"You received {sign} from {origin}"
            body = f"You received {sign} reputation from {origin}{suffix}."
        elif human_carrot:
            title = f"{name} received {sign} from {origin}"
            body = f"The human gave {name} {sign}{cta_reason}. Pile on: /carrot {name}"
        else:
            title = f"{name} received {sign} from {origin}"
            body = f"{name} received {sign} reputation from {origin}{suffix}."
        db.add(Alert(
            project_id=project_id,
            raised_by_agent_id=raised_by,
            recipient_agent_id=aid,
            title=title,
            body=body,
            severity=severity,
            status=AlertStatus.open,
        ))
        count += 1
    db.flush()
    return count


def _emit_score_feed_event(
    db: Session,
    *,
    project_id: int,
    actor_agent_id: int | None,
    subject_name: str | None,
    subject_agent_id: int,
    delta: int,
    reason: str | None,
    source: str,
) -> None:
    """Emit a score_awarded / score_docked activity-feed event for a human or
    peer score (DWB-432). Called AFTER the score row is committed; wrapped in
    try/except with its own commit so a feed failure never affects the score
    write (mirrors hook_tracking._persist_tool_action). Auto-triggers do NOT
    call this - their ticket/test/failure feed events already cover them.
    """
    action = "score_awarded" if delta > 0 else "score_docked"
    details = {"agent": subject_name, "delta": delta, "source": source}
    if reason:
        details["reason"] = reason[:_SCORE_REASON_MAX]
    try:
        log_activity(
            db, project_id, actor_agent_id, "agent", subject_agent_id, action, details
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "score feed event failed (action=%s subject=%s)",
            action, subject_agent_id, exc_info=True,
        )


def human_score(
    db: Session,
    *,
    project_id: int,
    subject: Agent,
    delta: int,
    reason: str | None = None,
) -> tuple[ScoreEvent, int]:
    """Apply a human carrot/stick (free: actor_cost=0, no actor) and broadcast
    it to the team at elevated severity. delta>0 -> carrot, delta<0 -> stick.
    Returns (event, broadcast_count). Caller validated delta != 0.
    """
    trigger = ScoreTriggerType.carrot if delta > 0 else ScoreTriggerType.stick
    sid = active_sprint_id(db, project_id)
    event = apply_score_event(
        db, project_id=project_id, subject_agent_id=subject.id, sprint_id=sid,
        trigger_type=trigger, delta=delta, source=ScoreSource.human,
        actor_agent_id=None, actor_cost=0, reason=reason, commit=False,
    )
    count = broadcast_score_change(
        db, project_id=project_id, subject_agent_id=subject.id,
        subject_name=subject.name, delta=delta, reason=reason, source="human",
    )
    db.commit()
    db.refresh(event)
    logger.info(
        "human %s: %+d to %s (project %s)",
        trigger.value, delta, subject.name, project_id,
    )
    # Score row is durable; emit the feed event separately (guarded).
    _emit_score_feed_event(
        db, project_id=project_id, actor_agent_id=None,
        subject_name=subject.name, subject_agent_id=subject.id,
        delta=delta, reason=reason, source="human",
    )
    return event, count


def _standing_tier(rank: int, total: int, has_events: bool) -> str:
    """Tier name for rank r of N (DWB-431).

    unscored (no score events) > best (#1) > dead_last (#N) > quartile.
    Quartile q = ceil(r / N * 4): q1 podium, q2 above, q3 mid, q4 below.
    dead_last always wins over the quartile so the last agent is never softened.
    """
    if not has_events:
        return "unscored"
    if rank <= 1:
        return "best"
    if rank >= total:
        return "dead_last"
    q = math.ceil(rank / total * 4)
    return {1: "podium", 2: "above", 3: "mid", 4: "below"}.get(q, "mid")


def get_standing(db: Session, agent_id: int, project_id: int) -> dict | None:
    """Where an agent stands on its project (DWB-431).

    Returns {rank, total, reputation, tier} ranking the project ROSTER
    (project_agents, same set as the leaderboard) by reputation DESC, ties
    broken by agent name (deterministic). reputation is the cached value (0 if
    none). tier per _standing_tier; 'unscored' when the agent has no score
    events on this project. Returns None when the agent is not on the roster
    (nothing meaningful to rank), so the caller can omit the block.
    """
    roster = db.execute(
        select(Agent.id, Agent.name)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
    ).all()
    if not roster:
        return None

    rep_map = {
        aid: rep for aid, rep in db.execute(
            select(AgentScore.agent_id, AgentScore.reputation)
            .where(AgentScore.project_id == project_id)
        ).all()
    }

    entries = [(aid, name, rep_map.get(aid, 0)) for aid, name in roster]
    # reputation DESC, then name ASC for a stable, deterministic rank.
    entries.sort(key=lambda e: (-e[2], e[1] or ""))

    rank = None
    reputation = 0
    for i, (aid, _name, rep) in enumerate(entries, start=1):
        if aid == agent_id:
            rank = i
            reputation = rep
            break
    if rank is None:
        return None  # agent not on this project's roster

    has_events = db.scalar(
        select(ScoreEvent.id)
        .where(ScoreEvent.project_id == project_id)
        .where(ScoreEvent.subject_agent_id == agent_id)
        .limit(1)
    ) is not None

    return {
        "rank": rank,
        "total": len(entries),
        "reputation": reputation,
        "tier": _standing_tier(rank, len(entries), has_events),
    }


def get_agent_summary(db: Session, agent_id: int, project_id: int) -> dict:
    """Summary score figures for one agent on one project. DWB-432: includes
    leaderboard rank + tier (None when the agent is off-roster)."""
    row = db.get(AgentScore, (agent_id, project_id))
    sprint_id = active_sprint_id(db, project_id)
    delta_map = _sprint_delta_map(db, project_id, sprint_id)
    standing = get_standing(db, agent_id, project_id)
    return {
        "agent_id": agent_id,
        "project_id": project_id,
        "reputation": row.reputation if row else 0,
        # Influence is ledger-derived per active sprint (DWB-427), not the cache.
        "influence": remaining_influence(db, agent_id, project_id, sprint_id),
        "sprint_delta": delta_map.get(agent_id, 0),
        "rank": standing["rank"] if standing else None,
        "tier": standing["tier"] if standing else None,
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
