# Path: app/services/stick_redemption.py
# File: stick_redemption.py
# Created: 2026-09-15
# Purpose: Stick redemption (DWB-537): when a memory append carries a `redeem:<score_event_id>` token, automatically grant the appending agent HALF of that one stick back, exactly once, with every eligibility rule enforced here and the once-per-stick guard doubled by the DB unique index on score_event.redemption_of.
# Caller: app/services/agent.py (append_memory, after the file write succeeds)
# Callees: app/services/scoring.py (apply_score_event, active_sprint_id), app/models/score_event.py
# Data In: db: Session, appending agent + project, X-Agent-ID caller id, raw append content
# Data Out: dict {granted: bool, reason: str} (never raises to the caller)
# Last Modified: 2026-09-15 (DWB-544: half rounded up)

"""Stick redemption (DWB-537).

Miles ruling: a stuck agent earns back HALF of THAT stick, exactly once, fully
automatic, zero human review, abuse-proof at the API.

Trigger: the memory append body contains ``redeem:<score_event_id>`` (regex
defined once below). Evaluated AFTER the memory write succeeds; the append
itself never fails because of redemption. The append response carries the
verdict as ``redemption: {granted, reason}``.

Eligibility (ALL must hold, checked in this order):
  1. X-Agent-ID matches the path agent (the agent redeems its own stick only).
  2. The token parses to an existing score_event on the SAME project.
  3. subject_agent_id == the appending agent.
  4. trigger_type in REDEEMABLE_TRIGGERS and delta < 0 (a redemption row is
     never redeemable, nor is a positive or non-stick event).
  5. reverted_by is null (a reverted stick already cost nothing).
  6. created_at within REDEEM_WINDOW_HOURS.
  7. No prior redemption references it: a query check here, PLUS the unique
     index on score_event.redemption_of so a concurrent second grant raises
     IntegrityError and is reported as already redeemed.
  8. The note beyond the token is at least MIN_NOTE_CHARS characters.

Grant: one score_event, source=auto, trigger_type=redemption,
delta = (abs(stick.delta) + 1) // 2 (half rounded up, DWB-544), ref_type='score_event',
ref_id=<stick id>, actor null, actor_cost 0. Half of ONE stick only, never
cumulative, never stackable; only the FIRST token in the body is evaluated.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project
from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.services import scoring

logger = logging.getLogger(__name__)

# The ONE definition of the trigger token. Word-bounded so "redeem:12x" or
# "xredeem:12" do not match; first occurrence wins.
REDEEM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])redeem:(\d+)(?![A-Za-z0-9_])")

# Sticks older than this cannot be redeemed.
REDEEM_WINDOW_HOURS = 48

# The note surrounding the token must carry real content (a lesson, not a
# bare token) before the half-back is granted.
MIN_NOTE_CHARS = 120

# Only demerit-class triggers are redeemable. `redemption` is deliberately
# absent (redemption of a redemption, or of a reverted redemption, is refused).
REDEEMABLE_TRIGGERS = frozenset({
    ScoreTriggerType.stick,
    ScoreTriggerType.peer_demerit,
    ScoreTriggerType.audit_demerit,
})


def _verdict(granted: bool, reason: str) -> dict:
    return {"granted": granted, "reason": reason}


def parse_redeem_token(content: str) -> tuple[int | None, str]:
    """Return (score_event_id, content_with_token_removed).

    Only the first token is honoured; the remaining text (token stripped,
    whitespace collapsed at the ends) is what MIN_NOTE_CHARS measures.
    """
    m = REDEEM_TOKEN_RE.search(content or "")
    if m is None:
        return None, (content or "").strip()
    remainder = (content[: m.start()] + content[m.end():]).strip()
    return int(m.group(1)), remainder


def _prior_redemption_exists(db: Session, stick_id: int) -> bool:
    """Any redemption row (reverted or not) referencing this stick blocks a
    second grant: once per stick, ever."""
    existing = db.scalar(
        select(ScoreEvent.id)
        .where(ScoreEvent.trigger_type == ScoreTriggerType.redemption)
        .where(ScoreEvent.ref_type == "score_event")
        .where(ScoreEvent.ref_id == stick_id)
        .limit(1)
    )
    return existing is not None


def evaluate_redemption(
    db: Session,
    *,
    agent: Agent,
    project: Project,
    caller_agent_id: int | None,
    content: str,
) -> dict:
    """Run the eligibility chain for one memory-append body and grant the
    half-back when everything holds. Returns {granted, reason}; never raises
    (the caller has already landed the memory write and must return 201)."""
    stick_id, note = parse_redeem_token(content)
    if stick_id is None:
        return _verdict(False, "no redeem token in content")

    if caller_agent_id is None or caller_agent_id != agent.id:
        return _verdict(
            False,
            f"X-Agent-ID must match agent {agent.id} to redeem its own stick",
        )

    stick = db.get(ScoreEvent, stick_id)
    if stick is None or stick.project_id != project.id:
        return _verdict(
            False, f"score_event {stick_id} not found on project {project.prefix}"
        )
    if stick.subject_agent_id != agent.id:
        return _verdict(
            False, f"score_event {stick_id} was not given to agent {agent.id}"
        )
    if stick.trigger_type not in REDEEMABLE_TRIGGERS or stick.delta >= 0:
        return _verdict(
            False,
            f"score_event {stick_id} is not a redeemable stick "
            f"(trigger {stick.trigger_type.value}, delta {stick.delta})",
        )
    if stick.reverted_by is not None:
        return _verdict(
            False, f"score_event {stick_id} was reverted; nothing to redeem"
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    created = stick.created_at
    if created is not None and created.tzinfo is not None:
        created = created.astimezone(timezone.utc).replace(tzinfo=None)
    if created is None or now - created > timedelta(hours=REDEEM_WINDOW_HOURS):
        return _verdict(
            False,
            f"score_event {stick_id} is older than {REDEEM_WINDOW_HOURS}h; "
            f"redemption window closed",
        )

    if _prior_redemption_exists(db, stick_id):
        return _verdict(False, f"score_event {stick_id} already redeemed")

    if len(note) < MIN_NOTE_CHARS:
        return _verdict(
            False,
            f"note too short: {len(note)} chars beyond the token, "
            f"need at least {MIN_NOTE_CHARS}",
        )

    # DWB-544 (Miles ruling): half of the stick rounded UP. -1 -> +1, -3 -> +2.
    delta = (abs(stick.delta) + 1) // 2
    try:
        scoring.apply_score_event(
            db,
            project_id=project.id,
            subject_agent_id=agent.id,
            sprint_id=scoring.active_sprint_id(db, project.id),
            trigger_type=ScoreTriggerType.redemption,
            delta=delta,
            source=ScoreSource.auto,
            actor_agent_id=None,
            actor_cost=0,
            reason=f"redeemed stick #{stick_id} via memory note",
            ref_type="score_event",
            ref_id=stick_id,
            commit=True,
        )
    except IntegrityError:
        # Lost the race: another request granted this stick between our query
        # check and the insert. The unique index on redemption_of refused it.
        db.rollback()
        logger.info(
            "redemption race lost for stick %s (agent %s); already redeemed",
            stick_id, agent.id,
        )
        return _verdict(False, f"score_event {stick_id} already redeemed")

    logger.info(
        "redemption granted: +%d to agent %s for stick #%s (project %s)",
        delta, agent.id, stick_id, project.prefix,
    )
    return _verdict(True, f"redeemed stick #{stick_id}: +{delta}")
