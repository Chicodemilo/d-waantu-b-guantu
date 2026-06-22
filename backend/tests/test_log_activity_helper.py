# Path:          tests/test_log_activity_helper.py
# File:          test_log_activity_helper.py
# Created:       2026-06-19
# Purpose:       Unit tests for the canonical log_activity() semantic-event helper (DWB-408)
# Caller:        pytest
# Callees:       app.services.activity_log.log_activity + action-verb constants
# Data In:       Factory-created project/agent, in-process db_session
# Data Out:      Assertions on inserted ActivityLog rows and the no-double-log invariant
# Last Modified: 2026-06-19 (DWB-408)

"""Unit tests for log_activity() and the no-double-log action vocabulary."""

import json

from app.models.activity_log import ActivityLog
from app.services.activity_log import (
    MIDDLEWARE_ACTIONS,
    SEMANTIC_ACTIONS,
    log_activity,
)


class TestNoDoubleLogVocabulary:
    def test_semantic_and_middleware_actions_are_disjoint(self):
        # The no-double-log rule: a semantic verb must never collide with a
        # generic CRUD verb emitted by the middleware.
        assert SEMANTIC_ACTIONS.isdisjoint(MIDDLEWARE_ACTIONS)

    def test_middleware_actions_are_the_crud_set(self):
        assert MIDDLEWARE_ACTIONS == {"created", "updated", "deleted"}

    def test_expected_semantic_verbs_registered(self):
        # The verbs the downstream tickets (409/410/411) will emit.
        for verb in (
            "status_changed",
            "assigned",
            "reopened",
            "sprint_opened",
            "sprint_closed",
            "consolidation_acked",
            "session_opened",
            "session_closed",
        ):
            assert verb in SEMANTIC_ACTIONS


class TestLogActivityHelper:
    def _project_and_agent(self, client, make_project, make_agent):
        return make_project(), make_agent()

    def test_inserts_row_with_all_fields(self, db_session, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()

        row = log_activity(
            db_session,
            project["id"],
            agent["id"],
            "ticket",
            42,
            "status_changed",
            {"from": "todo", "to": "in_progress"},
        )

        assert row.id is not None  # flush assigned a PK
        assert row.project_id == project["id"]
        assert row.agent_id == agent["id"]
        assert row.entity_type == "ticket"
        assert row.entity_id == 42
        assert row.action == "status_changed"

    def test_dict_details_are_json_encoded(self, db_session, make_project):
        project = make_project()
        row = log_activity(
            db_session, project["id"], None, "ticket", 1, "assigned",
            {"agent": "Barry_DWB"},
        )
        assert isinstance(row.details, str)
        assert json.loads(row.details) == {"agent": "Barry_DWB"}

    def test_empty_dict_details_become_none(self, db_session, make_project):
        project = make_project()
        row = log_activity(db_session, project["id"], None, "ticket", 1, "reopened", {})
        assert row.details is None

    def test_none_details_stay_none(self, db_session, make_project):
        project = make_project()
        row = log_activity(db_session, project["id"], None, "sprint", 1, "sprint_opened", None)
        assert row.details is None

    def test_string_details_pass_through(self, db_session, make_project):
        project = make_project()
        row = log_activity(db_session, project["id"], None, "sprint", 1, "sprint_closed", '{"pre": "ser"}')
        assert row.details == '{"pre": "ser"}'

    def test_agent_id_may_be_none(self, db_session, make_project):
        project = make_project()
        row = log_activity(db_session, project["id"], None, "session", 1, "session_opened", {"open_method": "regex"})
        assert row.agent_id is None

    def test_row_is_queryable_in_same_session(self, db_session, make_project):
        project = make_project()
        row = log_activity(db_session, project["id"], None, "ticket", 7, "status_changed", {"from": "a", "to": "b"})
        fetched = db_session.get(ActivityLog, row.id)
        assert fetched is not None
        assert fetched.action == "status_changed"

    def test_helper_flushes_but_does_not_commit(self, db_session, make_project):
        # Flushed (PK assigned, visible in-session) but NOT committed: a
        # SEPARATE connection cannot see the uncommitted row. Proves the helper
        # only flushed and left commit to the caller's request-scoped session.
        from tests.conftest import engine

        project = make_project()
        row = log_activity(db_session, project["id"], None, "ticket", 9, "reopened", None)
        assert row.id is not None  # flush assigned a PK
        assert db_session.get(ActivityLog, row.id) is not None  # visible in-session

        with engine.connect() as other:
            seen = other.execute(
                ActivityLog.__table__.select().where(ActivityLog.id == row.id)
            ).first()
        assert seen is None  # uncommitted -> invisible to another connection
