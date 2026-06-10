# Path: tests/test_dwb_session_aggregates.py
# File: test_dwb_session_aggregates.py
# Created: 2026-06-10
# Purpose: Tests for DWB-346 list-row aggregates (tickets_made/completed/agents_active/ticket_summary) + headline column
# Caller: pytest
# Callees: GET /api/projects/{id}/sessions, POST /api/sessions/{id}/close,
#          GET /api/sessions/{id}, app.services.dwb_session_rollup.compute_list_aggregates
# Data In: per-test db_session, factory fixtures, hand-rolled DwbSession + Ticket + HookSession rows
# Data Out: Assertions on list-row shape, aggregates math, headline write+retrieve, backwards-compat fields
# Last Modified: 2026-06-10

"""DWB-346 coverage.

Four scopes pinned, mirroring the ticket's acceptance list:

  1. Aggregates correct -
       tickets_made, tickets_completed, agents_active, open_method,
       close_method computed from the session window. Filters by window
       are inclusive; rows outside the window are excluded; rows from
       other projects are excluded.

  2. Headline written and retrieved -
       POST close with `headline=...` persists; the row's headline shows
       up in both GET /api/sessions/{id} (detail) and the per-row body of
       GET /api/projects/{id}/sessions (list).

  3. ticket_summary derived correctly -
       For completed-in-window tickets that have an epic, the dominant
       epic's name + count formats as "Epic Name (N)". When no ticket
       completed in window or none have an epic, ticket_summary is None.

  4. List endpoint backwards compatible -
       The original six fields (id, opened_at, closed_at, total_tokens,
       total_time_seconds, status) keep their old shape and values; new
       fields are additive.

Tests drive the public endpoints end-to-end (no service-level mocks) so the
router-rollup-schema stack is verified together.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.ticket import Ticket, TicketStatus


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _naive_now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def insert_dwb_session(db_session):
    """Insert a DwbSession directly via the per-test session.

    Mirrors the fixture in test_dwb_session_rollup.py so the two suites
    stay consistent. `opened_offset_minutes` and `closed_offset_minutes`
    are *minutes ago*; pass closed_offset_minutes=None for an open
    session.
    """

    def _make(
        project_id,
        *,
        opened_offset_minutes,
        closed_offset_minutes=None,
        total_tokens=0,
        total_time_seconds=0,
        open_method=DwbOpenMethod.regex,
        close_method=None,
        close_reason=None,
        open_phrase=None,
        close_phrase=None,
        headline=None,
    ):
        now = _naive_now()
        row = DwbSession(
            project_id=project_id,
            opened_at=now - timedelta(minutes=opened_offset_minutes),
            closed_at=(
                None
                if closed_offset_minutes is None
                else now - timedelta(minutes=closed_offset_minutes)
            ),
            open_method=open_method,
            close_method=close_method,
            close_reason=close_reason,
            open_phrase=open_phrase,
            close_phrase=close_phrase,
            total_tokens=total_tokens,
            total_time_seconds=total_time_seconds,
            headline=headline,
        )
        db_session.add(row)
        db_session.flush()
        db_session.refresh(row)
        return row

    return _make


@pytest.fixture
def insert_hook_session(db_session):
    """Insert a HookSession row pre-linked to a DWB session."""

    def _make(
        *,
        project_id,
        agent_id,
        session_id,
        start_offset_minutes,
        end_offset_minutes=None,
        dwb_session_id=None,
        total_tokens=0,
    ):
        now = _naive_now()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            agent_id=agent_id,
            start_time=now - timedelta(minutes=start_offset_minutes),
            end_time=(
                None
                if end_offset_minutes is None
                else now - timedelta(minutes=end_offset_minutes)
            ),
            status=HookSessionStatus.completed
            if end_offset_minutes is not None
            else HookSessionStatus.active,
            session_type=HookSessionType.teammate,
            total_tokens=total_tokens,
            dwb_session_id=dwb_session_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


def _stamp_ticket_times(
    db_session,
    ticket_id: int,
    *,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    status: TicketStatus | None = None,
):
    """Backdate a ticket's created_at/completed_at directly.

    The /api/tickets POST stamps created_at = now() at insert time; tests
    need to anchor it inside or outside a synthetic session window. Going
    through the ORM rather than a raw SQL UPDATE so SQLAlchemy session
    bookkeeping stays correct under the per-test rollback fixture.
    """
    t = db_session.get(Ticket, ticket_id)
    if t is None:
        raise AssertionError(f"ticket {ticket_id} not found")
    if created_at is not None:
        t.created_at = created_at
    if completed_at is not None:
        t.completed_at = completed_at
    if status is not None:
        t.status = status
    db_session.flush()
    db_session.refresh(t)
    return t


# ---------------------------------------------------------------------------
# 1. Aggregates correct
# ---------------------------------------------------------------------------


class TestListAggregates:
    """tickets_made, tickets_completed, agents_active, open_method, close_method."""

    def test_aggregates_count_only_rows_in_session_window(
        self,
        client,
        make_project,
        make_epic,
        make_sprint,
        make_ticket,
        make_agent,
        db_session,
        insert_dwb_session,
        insert_hook_session,
    ):
        """The session window is [opened_at, closed_at] inclusive. Tickets
        created/completed before or after the window are excluded.
        agents_active counts distinct linked-hook-session agents only.
        """
        now = _naive_now()
        project = make_project()
        pid = project["id"]
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])

        # Session window: 120 minutes ago -> 30 minutes ago.
        session = insert_dwb_session(
            pid,
            opened_offset_minutes=120,
            closed_offset_minutes=30,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        win_start = now - timedelta(minutes=120)
        win_end = now - timedelta(minutes=30)

        # Two agents.
        agent_a = make_agent(project_id=pid)
        agent_b = make_agent(project_id=pid)
        agent_outside = make_agent(project_id=pid)

        # Tickets:
        #   in-window created + completed
        t_in_made_done = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
        )
        _stamp_ticket_times(
            db_session,
            t_in_made_done["id"],
            created_at=win_start + timedelta(minutes=5),
            completed_at=win_start + timedelta(minutes=30),
            status=TicketStatus.done,
        )

        #   in-window created only (not yet done)
        t_in_made_only = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
        )
        _stamp_ticket_times(
            db_session,
            t_in_made_only["id"],
            created_at=win_start + timedelta(minutes=10),
        )

        #   in-window completed, created BEFORE the window
        t_done_only = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
        )
        _stamp_ticket_times(
            db_session,
            t_done_only["id"],
            created_at=win_start - timedelta(minutes=60),
            completed_at=win_start + timedelta(minutes=20),
            status=TicketStatus.done,
        )

        #   created before, completed after the window (excluded entirely)
        t_outside = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
        )
        _stamp_ticket_times(
            db_session,
            t_outside["id"],
            created_at=win_start - timedelta(minutes=30),
            completed_at=win_end + timedelta(minutes=15),
            status=TicketStatus.done,
        )

        # Hook sessions:
        #   linked to this DWB session -> agent_a, agent_b counted
        insert_hook_session(
            project_id=pid,
            agent_id=agent_a["id"],
            session_id="hs-linked-a",
            start_offset_minutes=110,
            end_offset_minutes=80,
            dwb_session_id=session.id,
            total_tokens=500,
        )
        insert_hook_session(
            project_id=pid,
            agent_id=agent_b["id"],
            session_id="hs-linked-b",
            start_offset_minutes=90,
            end_offset_minutes=50,
            dwb_session_id=session.id,
            total_tokens=750,
        )
        # Same agent_a again, also linked -> still one distinct agent.
        insert_hook_session(
            project_id=pid,
            agent_id=agent_a["id"],
            session_id="hs-linked-a-2",
            start_offset_minutes=70,
            end_offset_minutes=40,
            dwb_session_id=session.id,
            total_tokens=120,
        )
        # Not linked (dwb_session_id=None) -> excluded from agents_active.
        insert_hook_session(
            project_id=pid,
            agent_id=agent_outside["id"],
            session_id="hs-orphan",
            start_offset_minutes=80,
            end_offset_minutes=60,
            dwb_session_id=None,
            total_tokens=999,
        )
        db_session.flush()

        r = client.get(f"/api/projects/{pid}/sessions")
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1, rows
        row = rows[0]

        assert row["id"] == session.id
        # 2 tickets created in window: t_in_made_done + t_in_made_only.
        assert row["tickets_made"] == 2, row
        # 2 tickets completed in window: t_in_made_done + t_done_only.
        # t_outside completed AFTER the window, excluded.
        assert row["tickets_completed"] == 2, row
        # 2 distinct linked agents (a, b); orphan hook excluded.
        assert row["agents_active"] == 2, row
        # Enum surfacing.
        assert row["open_method"] == DwbOpenMethod.regex.value
        assert row["close_method"] == DwbCloseMethod.regex.value

    def test_aggregates_exclude_other_projects(
        self,
        client,
        make_project,
        make_sprint,
        make_ticket,
        db_session,
        insert_dwb_session,
    ):
        """A ticket created in another project must not bleed into this
        project's aggregates even when its created_at falls in the window.
        """
        project_a = make_project()
        project_b = make_project()
        sprint_b = make_sprint(project_id=project_b["id"])

        session_a = insert_dwb_session(
            project_a["id"],
            opened_offset_minutes=90,
            closed_offset_minutes=10,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        # Ticket on project B, created in project A's session window.
        t_b = make_ticket(project_id=project_b["id"], sprint_id=sprint_b["id"])
        _stamp_ticket_times(
            db_session,
            t_b["id"],
            created_at=_naive_now() - timedelta(minutes=60),
            completed_at=_naive_now() - timedelta(minutes=30),
            status=TicketStatus.done,
        )
        db_session.flush()

        r = client.get(f"/api/projects/{project_a['id']}/sessions")
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == session_a.id
        assert row["tickets_made"] == 0
        assert row["tickets_completed"] == 0
        assert row["agents_active"] == 0

    def test_open_session_uses_now_as_window_end(
        self,
        client,
        make_project,
        make_sprint,
        make_ticket,
        db_session,
        insert_dwb_session,
    ):
        """For an open session (closed_at IS NULL) the window end is `now`,
        so a ticket created 10 minutes ago is still in-window for a session
        opened an hour ago. close_method is None for open sessions.
        """
        project = make_project()
        pid = project["id"]
        sprint = make_sprint(project_id=pid)

        session = insert_dwb_session(
            pid,
            opened_offset_minutes=60,
            closed_offset_minutes=None,
        )

        t = make_ticket(project_id=pid, sprint_id=sprint["id"])
        _stamp_ticket_times(
            db_session,
            t["id"],
            created_at=_naive_now() - timedelta(minutes=10),
        )
        db_session.flush()

        r = client.get(f"/api/projects/{pid}/sessions")
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == session.id
        assert row["status"] == "open"
        assert row["close_method"] is None
        assert row["tickets_made"] == 1


# ---------------------------------------------------------------------------
# 2. Headline written + retrieved
# ---------------------------------------------------------------------------


class TestHeadlineRoundTrip:
    """DWB-346: headline column written by close endpoint, surfaced by list +
    detail endpoints."""

    def test_close_with_headline_persists_and_shows_on_list_and_detail(
        self, client, make_project,
    ):
        project = make_project()
        pid = project["id"]

        opened_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        r_open = client.post("/api/sessions/open", json={
            "project_id": pid,
            "opened_at": opened_at,
            "open_method": "regex",
            "open_phrase": "you are archie",
        })
        assert r_open.status_code == 201, r_open.text
        sid = r_open.json()["id"]

        headline = "Wired session aggregates + headline column"
        r_close = client.post(f"/api/sessions/{sid}/close", json={
            "close_method": "regex",
            "close_reason": "explicit",
            "close_phrase": "later boss",
            "headline": headline,
        })
        assert r_close.status_code == 200, r_close.text
        # DwbSessionRead surfaces the headline on the close response.
        assert r_close.json()["headline"] == headline

        # Detail endpoint surfaces it.
        r_detail = client.get(f"/api/sessions/{sid}")
        assert r_detail.status_code == 200
        assert r_detail.json()["headline"] == headline

        # List endpoint surfaces it.
        r_list = client.get(f"/api/projects/{pid}/sessions")
        rows = r_list.json()
        match = next((r for r in rows if r["id"] == sid), None)
        assert match is not None
        assert match["headline"] == headline

    def test_close_without_headline_leaves_column_null(
        self, client, make_project,
    ):
        project = make_project()
        pid = project["id"]
        opened_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        r_open = client.post("/api/sessions/open", json={
            "project_id": pid,
            "opened_at": opened_at,
            "open_method": "regex",
        })
        sid = r_open.json()["id"]

        r_close = client.post(f"/api/sessions/{sid}/close", json={
            "close_method": "regex",
            "close_reason": "explicit",
        })
        assert r_close.status_code == 200
        assert r_close.json()["headline"] is None

        r_list = client.get(f"/api/projects/{pid}/sessions")
        rows = r_list.json()
        match = next((r for r in rows if r["id"] == sid), None)
        assert match is not None
        assert match["headline"] is None


# ---------------------------------------------------------------------------
# 3. ticket_summary derived correctly
# ---------------------------------------------------------------------------


class TestTicketSummary:
    """ticket_summary = "<epic.name> (<count>)" using completed-in-window
    tickets. Dominant epic wins; None when no tickets completed in window
    or none of the completed tickets have an epic."""

    def test_single_epic_summary_is_epic_name_plus_count(
        self,
        client,
        make_project,
        make_epic,
        make_sprint,
        make_ticket,
        db_session,
        insert_dwb_session,
    ):
        project = make_project()
        pid = project["id"]
        epic = make_epic(
            project_id=pid, name="Fixing time and token tracking"
        )
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])

        session = insert_dwb_session(
            pid,
            opened_offset_minutes=90,
            closed_offset_minutes=10,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        # 4 tickets done in window, all on the same epic.
        for i in range(4):
            t = make_ticket(project_id=pid, sprint_id=sprint["id"])
            _stamp_ticket_times(
                db_session,
                t["id"],
                created_at=_naive_now() - timedelta(minutes=80 - i),
                completed_at=_naive_now() - timedelta(minutes=70 - i),
                status=TicketStatus.done,
            )
        db_session.flush()

        r = client.get(f"/api/projects/{pid}/sessions")
        rows = r.json()
        match = next((r for r in rows if r["id"] == session.id), None)
        assert match is not None
        assert match["tickets_completed"] == 4
        assert match["ticket_summary"] == "Fixing time and token tracking (4)"

    def test_dominant_epic_wins_when_multiple(
        self,
        client,
        make_project,
        make_epic,
        make_sprint,
        make_ticket,
        db_session,
        insert_dwb_session,
    ):
        project = make_project()
        pid = project["id"]

        epic_minor = make_epic(project_id=pid, name="Minor cleanup")
        epic_dom = make_epic(project_id=pid, name="Sessions dashboard")
        sprint = make_sprint(project_id=pid, epic_id=epic_minor["id"])

        session = insert_dwb_session(
            pid,
            opened_offset_minutes=90,
            closed_offset_minutes=10,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        # 1 done on the minor epic, 3 done on the dominant.
        for epic_id, count in ((epic_minor["id"], 1), (epic_dom["id"], 3)):
            for i in range(count):
                t = make_ticket(
                    project_id=pid, sprint_id=sprint["id"], epic_id=epic_id,
                )
                _stamp_ticket_times(
                    db_session,
                    t["id"],
                    completed_at=_naive_now() - timedelta(minutes=50 + i),
                    status=TicketStatus.done,
                )
        db_session.flush()

        r = client.get(f"/api/projects/{pid}/sessions")
        match = next(
            (row for row in r.json() if row["id"] == session.id), None
        )
        assert match is not None
        assert match["tickets_completed"] == 4
        assert match["ticket_summary"] == "Sessions dashboard (3)"

    def test_no_completed_tickets_means_null_summary(
        self, client, make_project, insert_dwb_session,
    ):
        project = make_project()
        session = insert_dwb_session(
            project["id"],
            opened_offset_minutes=60,
            closed_offset_minutes=10,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        r = client.get(f"/api/projects/{project['id']}/sessions")
        match = next(
            (row for row in r.json() if row["id"] == session.id), None
        )
        assert match is not None
        assert match["tickets_completed"] == 0
        assert match["ticket_summary"] is None


# ---------------------------------------------------------------------------
# 4. List endpoint backwards-compatible
# ---------------------------------------------------------------------------


class TestListBackwardsCompat:
    """The pre-DWB-346 fields keep their old keys and values; new fields
    are additive."""

    def test_legacy_fields_unchanged(
        self, client, make_project, insert_dwb_session,
    ):
        project = make_project()
        session = insert_dwb_session(
            project["id"],
            opened_offset_minutes=45,
            closed_offset_minutes=5,
            total_tokens=12345,
            total_time_seconds=2400,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )

        r = client.get(f"/api/projects/{project['id']}/sessions")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]

        # Pre-DWB-346 contract: these keys exist with these exact values.
        assert row["id"] == session.id
        assert row["total_tokens"] == 12345
        assert row["total_time_seconds"] == 2400
        assert row["status"] == "closed"
        assert "opened_at" in row and row["opened_at"] is not None
        assert "closed_at" in row and row["closed_at"] is not None

        # DWB-346 additive keys present.
        for k in (
            "headline",
            "tickets_made",
            "tickets_completed",
            "agents_active",
            "open_method",
            "close_method",
            "ticket_summary",
        ):
            assert k in row, f"missing additive key: {k}"

        # The aggregates default to safe zero/None values when nothing in
        # the project lines up with the window.
        assert row["headline"] is None
        assert row["tickets_made"] == 0
        assert row["tickets_completed"] == 0
        assert row["agents_active"] == 0
        assert row["ticket_summary"] is None
        # The close enums round-trip the persisted values.
        assert row["close_method"] == DwbCloseMethod.idle_timeout.value
