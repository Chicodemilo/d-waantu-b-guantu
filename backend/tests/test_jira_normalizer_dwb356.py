# Path: tests/test_jira_normalizer_dwb356.py
# File: test_jira_normalizer_dwb356.py
# Created: 2026-06-10
# Purpose: Tests for DWB-356 - jira_sync now sees sprint_name + reporter because _normalize_issue surfaces them
# Caller: pytest
# Callees: app.services.jira._normalize_issue, app.services.jira._extract_active_sprint_name, app.services.jira_sync
# Data In: synthetic Jira REST payloads, fake injected client for the sync round-trip
# Data Out: Assertions on normalizer output keys, active-sprint selection rules, end-to-end snapshot population
# Last Modified: 2026-06-10

"""DWB-356 coverage.

The DWB-342 snapshot schema reserved jira_sprint_name and jira_reporter
columns, but the canonical Jira normalizer (`_normalize_issue`) did not
extract either field, so the sync wrote NULL to both. DWB-356 fixes the
normalizer:

  - `reporter` (issue.fields.reporter.displayName) - flattened next to
    `assignee` with the same shape.
  - `sprint_name` - the ACTIVE sprint name pulled out of the
    instance-specific sprint customfield (env-configurable, defaults to
    'customfield_10020'). Closed-only sprints map to None; mixed
    active+closed returns the active one; legacy '[Sprint@...]' string
    encoding is parsed as a fallback.

These tests pin the normalizer shape and the end-to-end snapshot
population once the sync ingests an issue with both fields populated.
"""

import pytest

from app.config import settings
from app.models.jira_ticket_snapshot import JiraTicketSnapshot
from app.services import jira as jira_service
from app.services import jira_sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_issue(
    *,
    key: str = "POR-1",
    status: str = "In Progress",
    assignee_name: str | None = "Alice",
    reporter_name: str | None = "Bob",
    summary: str = "Do the thing",
    sprint_payload=None,
    sprint_customfield: str | None = None,
):
    """Build a raw Jira issue payload (the shape _normalize_issue sees)."""
    sprint_field = sprint_customfield or settings.JIRA_SPRINT_CUSTOMFIELD
    fields = {
        "summary": summary,
        "status": {"name": status, "statusCategory": {"name": "In Progress"}},
        "assignee": {"displayName": assignee_name} if assignee_name else None,
        "reporter": {"displayName": reporter_name} if reporter_name else None,
        "issuetype": {"name": "Task"},
        "parent": None,
        "priority": {"name": "Medium"},
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
    }
    if sprint_payload is not None:
        fields[sprint_field] = sprint_payload
    return {"key": key, "id": "id-" + key, "fields": fields}


# ---------------------------------------------------------------------------
# 1. reporter extraction
# ---------------------------------------------------------------------------


class TestReporterExtraction:
    def test_normalize_surfaces_reporter_displayname(self):
        out = jira_service._normalize_issue(_raw_issue(reporter_name="Charlie"))
        assert out["reporter"] == "Charlie"

    def test_normalize_reporter_none_when_field_missing(self):
        # No reporter dict on fields - the normalizer falls back to None
        # via the `or {}` guard on the field lookup.
        raw = _raw_issue(reporter_name=None)
        out = jira_service._normalize_issue(raw)
        assert out["reporter"] is None

    def test_normalize_keeps_assignee_extraction_intact(self):
        """Belt: the new reporter line shouldn't break the existing
        assignee flattening. Same shape, same lookup."""
        out = jira_service._normalize_issue(
            _raw_issue(assignee_name="Alice", reporter_name="Bob"),
        )
        assert out["assignee"] == "Alice"
        assert out["reporter"] == "Bob"


# ---------------------------------------------------------------------------
# 2. sprint name extraction (Jira Cloud dict shape)
# ---------------------------------------------------------------------------


class TestSprintNameExtractionDictShape:
    """DWB-356 revised selection rule (2026-06-10): active > future > closed,
    newest sprint within each tier (highest id). The original "active only"
    rule blanked every row on FRAUDI because all real tickets were in
    closed-only sprints; users want to see WHICH sprint the work was in,
    even if that sprint has since closed."""

    def test_single_active_sprint_returns_its_name(self):
        raw = _raw_issue(sprint_payload=[
            {"id": 99, "name": "Sprint 66", "state": "active"},
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 66"

    def test_single_closed_sprint_returns_its_name(self):
        """REVISED: closed-only no longer returns None - we surface the
        sprint where the work historically happened."""
        raw = _raw_issue(sprint_payload=[
            {"id": 65, "name": "Sprint 65", "state": "closed"},
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 65"

    def test_mixed_active_and_closed_picks_active(self):
        raw = _raw_issue(sprint_payload=[
            {"id": 65, "name": "Sprint 65", "state": "closed"},
            {"id": 66, "name": "Sprint 66", "state": "active"},
            {"id": 67, "name": "Sprint 67", "state": "future"},
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 66"

    def test_closed_only_picks_most_recent_by_id(self):
        """Multiple closed sprints with no active: highest id wins as the
        most-recent sprint membership."""
        raw = _raw_issue(sprint_payload=[
            {"id": 63, "name": "Sprint 63", "state": "closed"},
            {"id": 65, "name": "Sprint 65", "state": "closed"},
            {"id": 64, "name": "Sprint 64", "state": "closed"},
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 65"

    def test_future_only_picks_most_recent_future(self):
        """REVISED: future-only no longer returns None - returns the
        most-recent future sprint as the place work is scheduled."""
        raw = _raw_issue(sprint_payload=[
            {"id": 67, "name": "Sprint 67", "state": "future"},
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 67"

    def test_closed_plus_future_picks_future_over_closed(self):
        """Priority tier: future (work scheduled) beats closed (work shipped)."""
        raw = _raw_issue(sprint_payload=[
            {"id": 65, "name": "Sprint 65", "state": "closed"},
            {"id": 67, "name": "Sprint 67", "state": "future"},
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 67"

    def test_empty_sprint_list_returns_none(self):
        raw = _raw_issue(sprint_payload=[])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] is None

    def test_missing_sprint_customfield_returns_none(self):
        # sprint_payload=None means we do not inject the customfield at all.
        raw = _raw_issue(sprint_payload=None)
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] is None


# ---------------------------------------------------------------------------
# 3. Legacy string-encoded sprint shape
# ---------------------------------------------------------------------------


class TestSprintNameExtractionLegacyString:
    """Older Jira returned sprint customfield values as strings like
    'com.atlassian.greenhopper.service.sprint.Sprint@1abc[id=66,...,name=Sprint 66,state=ACTIVE,...]'.
    The extractor's regex fallback parses these too."""

    def test_legacy_string_active_sprint_parsed(self):
        raw = _raw_issue(sprint_payload=[
            "com.atlassian.greenhopper.service.sprint.Sprint@1abc"
            "[id=66,rapidViewId=12,state=ACTIVE,name=Sprint 66,"
            "startDate=2026-06-01,endDate=2026-06-14]",
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 66"

    def test_legacy_string_closed_sprint_surfaces_name(self):
        """REVISED (2026-06-10): closed-only sprints surface their name now,
        not None. The user wants the historical sprint label visible."""
        raw = _raw_issue(sprint_payload=[
            "[id=65,name=Sprint 65,state=CLOSED]"
        ])
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Sprint 65"


# ---------------------------------------------------------------------------
# 4. Configurable customfield ID
# ---------------------------------------------------------------------------


class TestConfigurableCustomfield:
    def test_alt_customfield_id_picked_up_when_setting_changes(self, monkeypatch):
        """A non-default Jira instance can override the customfield ID via
        env (settings.JIRA_SPRINT_CUSTOMFIELD). The normalizer should
        read from the configured field, not from the default."""
        monkeypatch.setattr(settings, "JIRA_SPRINT_CUSTOMFIELD", "customfield_99999")
        raw = _raw_issue(
            sprint_payload=[{"id": 1, "name": "Alt Sprint", "state": "active"}],
            sprint_customfield="customfield_99999",
        )
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Alt Sprint"

    def test_setting_resolves_to_a_customfield(self):
        """Sanity: the setting resolves to SOME customfield_* id. The
        actual value may be overridden in .env per Jira instance (e.g.
        Roadvantage uses customfield_10021), so this test stays
        environment-agnostic and just pins the format."""
        assert settings.JIRA_SPRINT_CUSTOMFIELD.startswith("customfield_")


class TestSprintCustomfieldAutoDetect:
    """DWB-356 revised: when the configured field is absent on the issue,
    scan customfield_* keys for the sprint-shape fingerprint (list of dicts
    each carrying both `name` and `state`). Roadvantage uses 10021 not the
    Cloud default 10020; live-probed 2026-06-10."""

    def test_finds_sprint_on_roadvantage_customfield_10021(self):
        """Configured field (10020) is empty; sprint data lives on 10021.
        Auto-detect must find it and extract the name."""
        raw = {
            "key": "POR-1",
            "id": "1",
            "fields": {
                "summary": "x",
                "status": {"name": "Done"},
                "assignee": None,
                "reporter": None,
                "issuetype": {"name": "Task"},
                # The configured field is missing entirely.
                "customfield_10021": [
                    {"id": 988, "name": "POR Sprint - We are Dashboard",
                     "state": "closed", "boardId": 14},
                ],
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "POR Sprint - We are Dashboard"

    def test_autodetect_ignores_non_sprint_customfields(self):
        """A customfield that is not sprint-shaped (string, dict without
        state, empty list) is skipped; nothing is mis-detected as a
        sprint."""
        raw = {
            "key": "POR-2", "id": "2",
            "fields": {
                "summary": "x",
                "status": {"name": "Done"},
                "issuetype": {"name": "Task"},
                "customfield_10000": "some string",
                "customfield_10015": None,
                "customfield_10016": [],
                "customfield_10032": {"name": "looks like sprint but is dict"},
                "customfield_10022": "0|i00sfw:",
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] is None

    def test_autodetect_finds_arbitrary_customfield_id(self):
        """A hypothetical third Jira instance with customfield_99999.
        Shape-based scan finds it regardless of ID."""
        raw = {
            "key": "POR-3", "id": "3",
            "fields": {
                "summary": "x",
                "status": {"name": "Active"},
                "issuetype": {"name": "Task"},
                "customfield_99999": [
                    {"id": 1, "name": "Alpha", "state": "active"},
                ],
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["sprint_name"] == "Alpha"


# ---------------------------------------------------------------------------
# 5. End-to-end: sync populates the snapshot columns from the new fields
# ---------------------------------------------------------------------------


# Re-use the FakeReadOnlyJira pattern from test_jira_sync_dwb342.py so the
# round-trip exercises run_sync against the real diff loop, including the
# DWB-356 normalizer surface keys.
_READ_METHODS = frozenset({
    "batch_get_issues", "get_issue", "list_projects", "search_issues",
    "get_active_sprints", "get_sprint_issues",
})


class _FakeReadOnlyJira:
    """Local copy of the DWB-342 fake - kept here so this file is
    self-contained against future renames in the DWB-342 suite."""

    def __init__(self, issues_by_key):
        self._issues_by_key = issues_by_key
        self.calls = []

    def __getattr__(self, name):
        if name not in _READ_METHODS:
            raise AttributeError(
                f"FakeReadOnlyJira refuses access to '{name}' - read-only contract."
            )
        def _stub(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "batch_get_issues":
                keys = args[0] if args else kwargs.get("issue_keys", [])
                return [self._issues_by_key[k] for k in keys if k in self._issues_by_key]
            return []
        return _stub


def _normalized_issue(key, **overrides):
    """Build a normalized issue dict (post-`_normalize_issue` shape) for
    the sync's batch_get_issues mock. The DWB-356 keys are exposed
    inline so the sync can write them."""
    base = {
        "key": key,
        "id": "id-" + key,
        "summary": "synthetic",
        "status": "In Progress",
        "status_category": "In Progress",
        "assignee": "Alice",
        "reporter": "Bob",
        "issue_type": "Task",
        "parent_key": None,
        "parent_type": None,
        "priority": "Medium",
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
        "sprint_name": "Sprint 66",
    }
    base.update(overrides)
    return base


@pytest.fixture
def jira_project(db_session):
    from app.models.project import Project
    p = Project(
        prefix="J356",
        name="DWB-356 Test",
        jira_base_url="https://example.atlassian.net",
        jira_project_key="POR",
        repo_path="/tmp/j356",
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def make_linked_ticket(db_session, jira_project):
    from app.models.epic import Epic, EpicStatus
    from app.models.sprint import Sprint, SprintStatus
    from app.models.ticket import Ticket, TicketStatus

    epic = Epic(project_id=jira_project.id, name="E1", status=EpicStatus.open)
    db_session.add(epic)
    db_session.flush()
    sprint = Sprint(
        project_id=jira_project.id, epic_id=epic.id, name="S1",
        sprint_number=1, status=SprintStatus.active,
    )
    db_session.add(sprint)
    db_session.flush()
    counter = [200]

    def _make(jira_key):
        counter[0] += 1
        t = Ticket(
            project_id=jira_project.id, epic_id=epic.id, sprint_id=sprint.id,
            ticket_number=counter[0], ticket_key=f"J356-{counter[0]}",
            title="synthetic", status=TicketStatus.in_progress,
            jira_issue_key=jira_key,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return _make


class TestSyncRoundTripPopulatesNewSnapshotColumns:
    def test_sprint_name_and_reporter_persisted_after_sync(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-100")
        fake = _FakeReadOnlyJira({
            "POR-100": _normalized_issue(
                "POR-100", sprint_name="Sprint 66", reporter="Reporter Carol",
            ),
        })
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )
        assert counts["added"] == 1

        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-100",
        ).one()
        assert snap.jira_sprint_name == "Sprint 66"
        assert snap.jira_reporter == "Reporter Carol"

    def test_changed_reporter_counted_as_updated(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-101")
        fake_v1 = _FakeReadOnlyJira({
            "POR-101": _normalized_issue("POR-101", reporter="Original"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake_v1)

        fake_v2 = _FakeReadOnlyJira({
            "POR-101": _normalized_issue("POR-101", reporter="New Person"),
        })
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake_v2,
        )
        assert counts["updated"] == 1

        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-101",
        ).one()
        assert snap.jira_reporter == "New Person"
