# Path: tests/test_recap.py
# File: test_recap.py
# Created: 2026-09-14
# Purpose: Tests for the auto-generated sprint recap draft (DWB-512) - window sweep, format rules (#245), and scrubbing of internal keys / em dashes.
# Caller: pytest
# Callees: GET /api/projects/{id}/recap-draft, ORM models seeded directly
# Data In: lat_test DB rows
# Data Out: assertions
# Last Modified: 2026-09-14

from datetime import datetime, timedelta

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.ticket import Ticket, TicketStatus
from app.models.tl_message import TlMessage

_NOW = datetime.utcnow()


def _mk_ticket(db, project_id, sprint_id, epic_id, key, title, **overrides):
    t = Ticket(
        project_id=project_id,
        sprint_id=sprint_id,
        epic_id=epic_id,
        ticket_number=overrides.pop("ticket_number", abs(hash(key)) % 100000),
        ticket_key=key,
        title=title,
        **overrides,
    )
    db.add(t)
    db.flush()
    return t


class TestRecapDraft:
    def _seed(self, db_session, make_sprint):
        sprint = make_sprint(goal="Ship the recap sweep and kill silent-fail comms")
        pid = sprint["project_id"]
        eid = sprint["epic_id"]
        sid = sprint["id"]

        # done inside the 14-day window -> counted + surfaced
        _mk_ticket(
            db_session, pid, sid, eid, f"REC-{pid}-1",
            "Recap sweep endpoint shipped",
            status=TicketStatus.done,
            completed_at=_NOW - timedelta(days=2),
            updated_at=_NOW - timedelta(days=2),
            tokens_used=5000,
        )
        # done OUTSIDE the window -> excluded
        _mk_ticket(
            db_session, pid, sid, eid, f"REC-{pid}-2",
            "Ancient closed ticket",
            status=TicketStatus.done,
            completed_at=_NOW - timedelta(days=40),
            updated_at=_NOW - timedelta(days=40),
        )
        # open, created before window -> carried
        _mk_ticket(
            db_session, pid, sid, eid, f"REC-{pid}-3",
            "Old carried goal",
            status=TicketStatus.todo,
            created_at=_NOW - timedelta(days=30),
        )
        # open, created inside window -> fresh goal (not carried)
        _mk_ticket(
            db_session, pid, sid, eid, f"REC-{pid}-4",
            "Fresh in-window goal",
            status=TicketStatus.in_progress,
            created_at=_NOW - timedelta(days=1),
            updated_at=_NOW - timedelta(days=1),
        )

        db_session.add(
            DwbSession(
                project_id=pid,
                opened_at=_NOW - timedelta(days=3),
                open_method=DwbOpenMethod.regex,
                headline="Built the recap generator",
            )
        )
        db_session.flush()
        return pid

    def test_window_sweep_and_format(self, client, db_session, make_sprint, make_agent):
        pid = self._seed(db_session, make_sprint)
        agent = make_agent(project_id=pid)
        db_session.add(
            TlMessage(
                from_agent_id=agent["id"],
                from_project_id=pid,
                body="Fixed the silent-fail comms path this sprint",
                created_at=_NOW - timedelta(days=2),
            )
        )
        db_session.flush()

        r = client.get(f"/api/projects/{pid}/recap-draft")
        assert r.status_code == 200, r.text
        data = r.json()

        assert data["counts"]["tickets_closed"] == 1
        draft = data["draft"]

        # in-window done surfaces, out-of-window done does not
        assert "Recap sweep endpoint shipped" in draft
        assert "Ancient closed ticket" not in draft

        # goals section: carried label on the old open, none on the fresh one
        assert "Old carried goal (carried)" in draft
        assert "Fresh in-window goal" in draft
        assert "Fresh in-window goal (carried)" not in draft

        # session + tl-channel content present
        assert "Built the recap generator" in draft
        assert "Fixed the silent-fail comms path this sprint" in draft

        # required sections
        for section in ("**THIS SPRINT GOALS**", "**WORKFLOW**", "**PERSONAL**"):
            assert section in draft

    def test_window_param_narrows_sweep(self, client, db_session, make_sprint):
        pid = self._seed(db_session, make_sprint)
        # 1-day window drops the done-2-days-ago ticket
        r = client.get(f"/api/projects/{pid}/recap-draft?window_days=1")
        assert r.status_code == 200
        data = r.json()
        assert data["window_days"] == 1
        assert data["counts"]["tickets_closed"] == 0
        assert "Recap sweep endpoint shipped" not in data["draft"]

    def test_scrubs_internal_keys_and_em_dashes(
        self, client, db_session, make_sprint
    ):
        sprint = make_sprint(goal="Theme goal")
        pid = sprint["project_id"]
        _mk_ticket(
            db_session, sprint["project_id"], sprint["id"], sprint["epic_id"],
            f"REC-{pid}-scrub",
            "Fix DWB-512 regression — restore the write",
            status=TicketStatus.done,
            completed_at=_NOW - timedelta(days=1),
            updated_at=_NOW - timedelta(days=1),
        )
        db_session.flush()

        r = client.get(f"/api/projects/{pid}/recap-draft")
        assert r.status_code == 200
        draft = r.json()["draft"]
        assert "—" not in draft  # no em dash
        assert "–" not in draft  # no en dash
        assert "DWB-512" not in draft  # internal key scrubbed
        assert "restore the write" in draft  # surrounding text kept

    def test_404_for_missing_project(self, client):
        r = client.get("/api/projects/999999/recap-draft")
        assert r.status_code == 404

    def test_window_bounds_validated(self, client, db_session, make_sprint):
        pid = self._seed(db_session, make_sprint)
        assert client.get(f"/api/projects/{pid}/recap-draft?window_days=0").status_code == 422
        assert client.get(f"/api/projects/{pid}/recap-draft?window_days=91").status_code == 422
