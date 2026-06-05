# Path: tests/test_overhead_bucket_invariant.py
# File: test_overhead_bucket_invariant.py
# Created: 2026-06-05
# Purpose: Invariant + unit tests for DWB-305 — overhead bucket integrity
# Caller: pytest
# Callees: app.services.tracking, app.models.project
# Data In: pytest fixtures (make_project, make_agent)
# Data Out: assertions
# Last Modified: 2026-06-05

"""DWB-305 — Overhead bucket integrity.

Guarantees that for every project at every snapshot:

    project.tl_overhead_tokens + project.pm_overhead_tokens
        == SUM(tracking_log.tokens
               WHERE event_type='overhead_token_report'
                 AND project_id = project.id)

The atomic increment lives in `tracking.log_overhead_tokens()` (see
hook_tracking.py for the callers). These tests cover (a) PM vs non-PM
classification, (b) drift-free multi-call accumulation, and (c) the
global invariant walked across all projects.
"""

from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.project import Project
from app.models.tracking_log import TrackingLog
from app.services import tracking


def _overhead_total(db, project_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(TrackingLog.tokens), 0))
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.event_type == "overhead_token_report")
    ) or 0


def test_log_overhead_tokens_team_lead_increments_tl_bucket(
    db_session, make_project, make_agent
):
    """A team-lead overhead token report lands in tl_overhead_tokens."""
    project = make_project()
    tl = make_agent(project_id=project["id"], role="team-lead")

    tracking.log_overhead_tokens(db_session, project["id"], tl["id"], 5_000)

    p = db_session.get(Project, project["id"])
    assert p.tl_overhead_tokens == 5_000
    assert p.pm_overhead_tokens == 0
    assert p.tl_overhead_tokens + p.pm_overhead_tokens == _overhead_total(
        db_session, project["id"]
    )


def test_log_overhead_tokens_pm_increments_pm_bucket(
    db_session, make_project, make_agent
):
    """A PM overhead token report lands in pm_overhead_tokens, not tl."""
    project = make_project()
    pm = make_agent(project_id=project["id"], role="pm")

    tracking.log_overhead_tokens(db_session, project["id"], pm["id"], 3_000)

    p = db_session.get(Project, project["id"])
    assert p.pm_overhead_tokens == 3_000
    assert p.tl_overhead_tokens == 0
    assert p.tl_overhead_tokens + p.pm_overhead_tokens == _overhead_total(
        db_session, project["id"]
    )


def test_log_overhead_tokens_non_pm_role_falls_back_to_tl_bucket(
    db_session, make_project, make_agent
):
    """A worker (non-pm) classified as overhead falls into tl_overhead.

    This is the defensive branch: any role other than 'pm' lands in
    tl_overhead so the invariant always closes — there is no escape
    hatch that updates tracking_log without touching a project bucket.
    """
    project = make_project()
    worker = make_agent(project_id=project["id"], role="backend-worker")

    tracking.log_overhead_tokens(db_session, project["id"], worker["id"], 1_500)

    p = db_session.get(Project, project["id"])
    assert p.tl_overhead_tokens == 1_500
    assert p.pm_overhead_tokens == 0
    assert p.tl_overhead_tokens + p.pm_overhead_tokens == _overhead_total(
        db_session, project["id"]
    )


def test_log_overhead_tokens_accumulates_without_drift(
    db_session, make_project, make_agent
):
    """Repeated log_overhead_tokens calls keep buckets in sync with tracking_log."""
    project = make_project()
    tl = make_agent(project_id=project["id"], role="team-lead")
    pm = make_agent(project_id=project["id"], role="pm")

    tracking.log_overhead_tokens(db_session, project["id"], tl["id"], 1_000)
    tracking.log_overhead_tokens(db_session, project["id"], pm["id"], 250)
    tracking.log_overhead_tokens(db_session, project["id"], tl["id"], 4_000)
    tracking.log_overhead_tokens(db_session, project["id"], pm["id"], 750)

    p = db_session.get(Project, project["id"])
    assert p.tl_overhead_tokens == 5_000
    assert p.pm_overhead_tokens == 1_000
    assert p.tl_overhead_tokens + p.pm_overhead_tokens == _overhead_total(
        db_session, project["id"]
    )


def test_log_overhead_tokens_zero_is_noop(db_session, make_project, make_agent):
    """Logging zero tokens still writes a row but moves no bucket."""
    project = make_project()
    tl = make_agent(project_id=project["id"], role="team-lead")

    tracking.log_overhead_tokens(db_session, project["id"], tl["id"], 0)

    p = db_session.get(Project, project["id"])
    assert p.tl_overhead_tokens == 0
    assert p.pm_overhead_tokens == 0
    assert p.tl_overhead_tokens + p.pm_overhead_tokens == _overhead_total(
        db_session, project["id"]
    )


def test_overhead_bucket_invariant_across_all_projects(
    db_session, make_project, make_agent
):
    """The bucket sum must equal the project_total.overhead_tokens for every
    project visible in the test DB. Failure message lists offenders so a
    real drift surfaces clearly.
    """
    project_a = make_project()
    project_b = make_project()
    tl_a = make_agent(project_id=project_a["id"], role="team-lead")
    pm_a = make_agent(project_id=project_a["id"], role="pm")
    tl_b = make_agent(project_id=project_b["id"], role="team-lead")

    tracking.log_overhead_tokens(db_session, project_a["id"], tl_a["id"], 2_000)
    tracking.log_overhead_tokens(db_session, project_a["id"], pm_a["id"], 500)
    tracking.log_overhead_tokens(db_session, project_b["id"], tl_b["id"], 9_000)

    offenders: list[tuple[int, int, int, int]] = []
    for p in db_session.scalars(select(Project)).all():
        total = _overhead_total(db_session, p.id)
        bucket_sum = p.tl_overhead_tokens + p.pm_overhead_tokens
        if bucket_sum != total:
            offenders.append((p.id, bucket_sum, total, total - bucket_sum))

    assert not offenders, (
        "overhead bucket invariant violated: "
        + ", ".join(
            f"project_id={pid} buckets={bs} project_total={t} delta={d}"
            for pid, bs, t, d in offenders
        )
    )
