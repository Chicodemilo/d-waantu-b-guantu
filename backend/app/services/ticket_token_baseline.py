# Path: app/services/ticket_token_baseline.py
# File: ticket_token_baseline.py
# Created: 2026-09-15
# Purpose: Ticket token baseline (DWB-546): per done-ticket token/time rows plus per-sprint count/median/mean/p90 aggregates, the measurement floor for "do node-aware agents spend fewer tokens". Attribution is reused from app/services/tracking.py, never recomputed here.
# Caller: app/routers/projects.py (GET /api/projects/{id}/ticket-token-baseline)
# Callees: app/services/tracking.py (compute_ticket_tokens, compute_ticket_time), app/models/ticket.py, app/models/agent.py
# Data In: db: Session, project_id, optional sprint_id, optional since datetime
# Data Out: dict {project_id, ticket_count, tickets: [...], sprints: [...]}
# Last Modified: 2026-09-15 (DWB-546)

"""Ticket token baseline (DWB-546).

Purpose: measure whether node-aware agents reduce tokens. This is the BEFORE
picture, so it must be honest about the data it reports rather than smoothing
it: every done ticket appears, including the ones attributed zero tokens.

Attribution is NOT reimplemented here. `tracking.compute_ticket_tokens` (sum of
`token_report` rows in tracking_log, which is where the hook lifecycle lands an
agent's tokens) and `tracking.compute_ticket_time` (paired start/stop rows) are
the same functions the tracking summary and the session rollup use, so a number
here always matches the number those surfaces show for the same ticket.

`tokens_used` is the attributed value from tracking_log. `stored_tokens_used`
is the denormalized `tickets.tokens_used` column, which has a manual-increment
path that writes no tracking_log row. They agree today; the pair is exposed so
a future divergence is visible instead of silently changing the baseline.

`node_aware` is a placeholder: False for every ticket today. DWB-545 follow-ups
set it once node-aware spawns are distinguishable, and the comparison then runs
against these same rows.

KNOWN DATA CAVEAT (DWB-539): token attribution is currently incomplete. A
ticket whose worker never posted a token report reads 0 here, which is an
attribution gap, not a free ticket. `zero_token_ticket_count` per sprint makes
the size of that gap explicit, and aggregates are computed over the attributed
tickets only (see `_aggregate`) so a sprint's median is not dragged to 0 by
unattributed rows. Both the attributed and the zero counts are reported.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.ticket import Ticket, TicketStatus
from app.services import tracking


def _percentile(sorted_values: list[int], fraction: float) -> float:
    """Linear-interpolated percentile over a pre-sorted list.

    Matches the common "nearest rank with interpolation" definition (the one
    numpy's default `linear` method uses) so a p90 quoted from this endpoint
    can be reproduced by anyone checking the numbers by hand.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return float(sorted_values[low] * (1 - weight) + sorted_values[high] * weight)


def _median(sorted_values: list[int]) -> float:
    return _percentile(sorted_values, 0.5)


def _aggregate(sprint_id: int | None, rows: list[dict]) -> dict:
    """One sprint's aggregates.

    `ticket_count` counts every done ticket in the sprint. The statistics are
    computed over tickets with attributed tokens > 0 only: a zero row is an
    attribution gap (DWB-539), and folding those into the median would report a
    token cost the team did not actually achieve. `zero_token_ticket_count`
    carries the gap so the reader can weigh the sample.
    """
    attributed = sorted(r["tokens_used"] for r in rows if r["tokens_used"] > 0)
    return {
        "sprint_id": sprint_id,
        "ticket_count": len(rows),
        "attributed_ticket_count": len(attributed),
        "zero_token_ticket_count": len(rows) - len(attributed),
        "median_tokens": _median(attributed),
        "mean_tokens": (
            float(sum(attributed)) / len(attributed) if attributed else 0.0
        ),
        "p90_tokens": _percentile(attributed, 0.9),
        "total_tokens": sum(attributed),
    }


def get_ticket_token_baseline(
    db: Session,
    *,
    project_id: int,
    sprint_id: int | None = None,
    since: datetime | None = None,
) -> dict:
    """Per done-ticket token/time rows for a project, plus per-sprint aggregates.

    sprint_id narrows to one sprint; since keeps tickets completed at or after
    that timestamp (naive UTC, matching the stored `completed_at`). Tickets are
    ordered by sprint then ticket id, and sprints in the aggregate list follow
    first appearance so the newest sprint is not buried.
    """
    stmt = (
        select(Ticket, Agent.name)
        .outerjoin(Agent, Ticket.assigned_agent_id == Agent.id)
        .where(Ticket.project_id == project_id)
        .where(Ticket.status == TicketStatus.done)
        .order_by(Ticket.sprint_id.asc(), Ticket.id.asc())
    )
    if sprint_id is not None:
        stmt = stmt.where(Ticket.sprint_id == sprint_id)
    if since is not None:
        cutoff = since.replace(tzinfo=None) if since.tzinfo else since
        stmt = stmt.where(Ticket.completed_at.isnot(None))
        stmt = stmt.where(Ticket.completed_at >= cutoff)

    tickets: list[dict] = []
    by_sprint: dict[int | None, list[dict]] = {}
    for ticket, agent_name in db.execute(stmt).all():
        row = {
            "ticket_id": ticket.id,
            "ticket_key": ticket.ticket_key,
            "sprint_id": ticket.sprint_id,
            "assigned_agent_id": ticket.assigned_agent_id,
            "assigned_agent_name": agent_name,
            # int(): MySQL SUM() hands back Decimal, which does not mix with
            # the float arithmetic in _percentile and would serialize oddly.
            "tokens_used": int(tracking.compute_ticket_tokens(db, ticket.id) or 0),
            "stored_tokens_used": int(ticket.tokens_used or 0),
            "time_seconds": int(tracking.compute_ticket_time(db, ticket.id) or 0),
            "completed_at": (
                ticket.completed_at.isoformat() if ticket.completed_at else None
            ),
            # DWB-546: placeholder, False everywhere until DWB-545 follow-ups
            # can tell a node-aware run from a plain one.
            "node_aware": False,
        }
        tickets.append(row)
        by_sprint.setdefault(ticket.sprint_id, []).append(row)

    return {
        "project_id": project_id,
        "ticket_count": len(tickets),
        "tickets": tickets,
        "sprints": [_aggregate(sid, rows) for sid, rows in by_sprint.items()],
    }
