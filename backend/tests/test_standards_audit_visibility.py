# Path: tests/test_standards_audit_visibility.py
# File: test_standards_audit_visibility.py
# Created: 2026-08-12 (DWB-028)
# Purpose: DWB-028 acceptance - every audit POST raises a visible Alert (info on
#          pass / warning on reject, title carrying id/verdict/ticket/violations)
#          and attributes the write to the fixed The_Auditor agent in the
#          activity feed.
# Caller: pytest
# Callees: POST /api/standards-audits, app.models (alert, activity_log, agent)
# Data In: Factory-created project/agents/ticket via conftest fixtures
# Data Out: Assertions on Alert + ActivityLog rows
# Last Modified: 2026-08-12 (DWB-028)

import pytest
from sqlalchemy import select

from app.models.activity_log import ActivityLog
from app.models.alert import Alert, AlertSeverity


@pytest.fixture
def auditor(make_agent):
    """The fixed The_Auditor system agent (the migration seeds this in prod; the
    service resolves it by name). Created here so tests don't depend on the
    migration having run against the create_all test schema."""
    return make_agent(name="The_Auditor", role="auditor", api_key="the-auditor-key")


def _create_audit(client, project_id, verdict, **overrides):
    payload = {
        "project_id": project_id,
        "pr_ref": "PR#7",
        "verdict": verdict,
        "violations": overrides.pop("violations", []),
    }
    payload.update(overrides)
    r = client.post("/api/standards-audits", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _alerts_for_project(db, project_id):
    return list(db.scalars(
        select(Alert).where(Alert.project_id == project_id)
    ).all())


class TestAuditAlert:
    def test_pass_audit_raises_info_alert(self, client, db_session, make_project, auditor):
        p = make_project()
        audit = _create_audit(client, p["id"], "pass")
        alerts = _alerts_for_project(db_session, p["id"])
        assert len(alerts) == 1
        a = alerts[0]
        assert a.severity == AlertSeverity.info
        assert a.raised_by_agent_id == auditor["id"]
        assert f"Standards audit #{audit['id']}: PASS" in a.title
        assert "0 violations" in a.title

    def test_reject_audit_raises_warning_alert_with_counts(
        self, client, db_session, make_project, auditor
    ):
        p = make_project()
        audit = _create_audit(
            client, p["id"], "reject",
            violations=[
                {"rule": "headers", "file": "a.py"},
                {"rule": "services", "file": "b.py"},
            ],
        )
        alerts = _alerts_for_project(db_session, p["id"])
        assert len(alerts) == 1
        a = alerts[0]
        assert a.severity == AlertSeverity.warning
        assert f"Standards audit #{audit['id']}: REJECT" in a.title
        assert "2 violations" in a.title

    def test_alert_title_includes_ticket_key_when_linked(
        self, client, db_session, make_project, make_ticket, auditor
    ):
        p = make_project()
        ticket = make_ticket(project_id=p["id"])
        _create_audit(
            client, p["id"], "reject",
            ticket_id=ticket["id"],
            violations=[{"rule": "headers"}],
        )
        a = _alerts_for_project(db_session, p["id"])[0]
        assert ticket["ticket_key"] in a.title
        assert a.ticket_id == ticket["id"]
        # Singular when exactly one violation.
        assert "1 violation" in a.title and "1 violations" not in a.title

    def test_singular_vs_plural_violation_wording(
        self, client, db_session, make_project, auditor
    ):
        p = make_project()
        _create_audit(client, p["id"], "pass")  # 0 -> plural
        a = _alerts_for_project(db_session, p["id"])[0]
        assert "0 violations" in a.title


class TestAuditAttribution:
    def test_activity_attributes_to_the_auditor(
        self, client, db_session, make_project, auditor
    ):
        p = make_project()
        audit = _create_audit(client, p["id"], "reject", violations=[{"rule": "x"}])
        rows = list(db_session.scalars(
            select(ActivityLog)
            .where(ActivityLog.entity_type == "standards_audit")
            .where(ActivityLog.entity_id == audit["id"])
            .where(ActivityLog.action == "standards_audit_recorded")
        ).all())
        assert len(rows) == 1
        assert rows[0].agent_id == auditor["id"]

    def test_no_auditor_agent_still_creates_audit(
        self, client, db_session, make_project
    ):
        # No The_Auditor and no roster -> alert is skipped, but the audit write
        # must still succeed (visibility is best-effort).
        p = make_project()
        r = client.post("/api/standards-audits", json={
            "project_id": p["id"], "pr_ref": "PR#9", "verdict": "pass",
        })
        assert r.status_code == 201
        assert _alerts_for_project(db_session, p["id"]) == []
