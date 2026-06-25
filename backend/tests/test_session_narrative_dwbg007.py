# Path: tests/test_session_narrative_dwbg007.py
# File: test_session_narrative_dwbg007.py
# Created: 2026-06-25
# Purpose: Backend tests for the P1 Session Recall narrative layer — _redact_narrative
#          secret scrubbing (DWBG-008), narrative persistence + provenance on a
#          conscious close (DWBG-007), and entity_keywords purge on project delete
#          (DWBG-004). Complements the frontend SessionSummary tests (DWBG-009).
# Caller: pytest
# Callees: app.services.dwb_session (_redact_narrative, close_session), the
#          /api/projects + /api/sessions endpoints, EntityKeyword model
# Data In: per-test db_session + make_project fixture + hand-rolled session rows
# Data Out: assertions on redacted narrative content, persisted narrative/provenance,
#           and entity_keywords rows after delete
# Last Modified: 2026-06-25

"""P1 Session Recall narrative layer — backend coverage (DWBG-004/007/008)."""

from datetime import datetime

from sqlalchemy import select

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.entity_keyword import EntityKeyword
from app.services.dwb_session import _redact_narrative, close_session


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


def _open_session(db_session, project_id):
    row = DwbSession(
        project_id=project_id,
        opened_at=_naive_now(),
        open_method=DwbOpenMethod.ai_confident,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# DWBG-008: _redact_narrative — pure function, no DB
# ---------------------------------------------------------------------------


class TestRedactNarrative:
    def _flat(self, narrative):
        import json

        return json.dumps(_redact_narrative(narrative))

    def test_scrubs_api_keys_and_provider_tokens(self):
        flat = self._flat({"lead": "x", "sections": [{"title": "t", "bullets": [
            "sk-ABCD1234efgh5678ijkl90mn",
            "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
            "AKIAIOSFODNN7EXAMPLE",
            "xoxb-123456789012-abcdefghijkl",
        ]}]})
        for secret in ("sk-ABCD1234", "ghp_aBcDeF", "AKIAIOSFODNN7EXAMPLE", "xoxb-1234567890"):
            assert secret not in flat
        assert "[REDACTED]" in flat

    def test_scrubs_jwt_and_bearer_token_fully(self):
        # Regression: the key=value rule used to consume only "Bearer" and leave
        # the trailing token; specific patterns must run first.
        flat = self._flat({"lead": "Authorization: Bearer abcdefghijklmnop1234567890XYZ",
                           "sections": [{"title": "t", "bullets": [
                               "eyJhbGciOiJIUzI1Niocccc.eyJzdWIiOiIxMjM0NToo.SflKxwRJSMeKKF2QT4"]}]})
        assert "abcdefghijklmnop1234567890XYZ" not in flat
        assert "eyJhbGciOiJIUzI1Niocccc" not in flat

    def test_scrubs_pii_ssn_and_card(self):
        flat = self._flat({"lead": "SSN 123-45-6789 and card 4111 1111 1111 1111",
                           "sections": []})
        assert "123-45-6789" not in flat
        assert "4111 1111 1111 1111" not in flat

    def test_scrubs_labelled_keyvalue_secrets(self):
        flat = self._flat({"lead": "password: hunter2supersecret", "sections": []})
        assert "hunter2supersecret" not in flat

    def test_preserves_normal_prose(self):
        flat = self._flat({"lead": "Shipped the migration cleanly today.",
                           "sections": [{"title": "Next", "bullets": ["start P2 FULLTEXT search"]}]})
        assert "Shipped the migration cleanly today." in flat
        assert "start P2 FULLTEXT search" in flat

    def test_recurses_nested_lists_and_dicts(self):
        out = _redact_narrative({"sections": [{"title": "k", "bullets": [
            "ok line", "leak sk-DEADBEEF1234567890abcd"]}]})
        bullets = out["sections"][0]["bullets"]
        assert bullets[0] == "ok line"
        assert "sk-DEADBEEF" not in bullets[1] and "[REDACTED]" in bullets[1]


# ---------------------------------------------------------------------------
# DWBG-007: narrative persistence + provenance on close
# ---------------------------------------------------------------------------


class TestNarrativePersistOnClose:
    def test_conscious_close_persists_narrative_and_provenance(self, db_session, make_project):
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        narrative = {"lead": "Did the thing", "sections": [{"title": "Decisions", "bullets": ["chose A"]}]}
        close_session(
            db_session, row,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
            headline="did the thing", narrative=narrative,
        )
        assert row.narrative == narrative
        assert row.narrative_author == "tl"
        assert row.narrative_generated_at is not None

    def test_close_without_narrative_leaves_it_null(self, db_session, make_project):
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        close_session(
            db_session, row,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
            headline="no narrative supplied",
        )
        assert row.narrative is None
        assert row.narrative_author is None

    def test_redaction_applied_through_close_path(self, db_session, make_project):
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        narrative = {"lead": "leaked api_key=sk-SECRET1234567890abcd here", "sections": []}
        close_session(
            db_session, row,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
            headline="redaction test", narrative=narrative,
        )
        import json
        assert "sk-SECRET1234567890abcd" not in json.dumps(row.narrative)

    def test_supplied_narrative_does_not_clobber_summary(self, db_session, make_project):
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        close_session(
            db_session, row,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
            headline="baseline intact", narrative={"lead": "n", "sections": []},
        )
        # The deterministic synthesizer still ran and set the summary baseline.
        assert row.summary is not None


# ---------------------------------------------------------------------------
# DWBG-004: entity_keywords purged on project delete
# ---------------------------------------------------------------------------


class TestEntityKeywordPurgeOnProjectDelete:
    def test_delete_project_purges_session_keywords(self, db_session, make_project, client):
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        db_session.add(EntityKeyword(
            entity_type="dwb_session", entity_id=row.id,
            keyword="recall", weight=3, source="test",
        ))
        db_session.flush()

        def kw_count():
            return len(db_session.execute(
                select(EntityKeyword)
                .where(EntityKeyword.entity_type == "dwb_session")
                .where(EntityKeyword.entity_id == row.id)
            ).scalars().all())

        assert kw_count() == 1
        r = client.delete(f"/api/projects/{proj['id']}")
        assert r.status_code == 204
        db_session.expire_all()
        assert kw_count() == 0
