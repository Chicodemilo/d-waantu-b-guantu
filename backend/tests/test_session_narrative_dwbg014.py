# Path: tests/test_session_narrative_dwbg014.py
# File: test_session_narrative_dwbg014.py
# Created: 2026-06-25
# Purpose: Backend tests for the DWBG-014 summarizer — pure JSON parsing
#          (_parse_narrative), generate_narrative best-effort behavior (DWBG-017:
#          mocked at the PROVIDER seam, not the SDK), the auto-on-close wiring +
#          force_session_writeup gate (close_session), TL-narrative precedence,
#          redaction-through-summarizer, and the on-demand
#          POST /api/sessions/{id}/generate-narrative endpoint. Inference is MOCKED
#          throughout — no real backend in tests. Provider-level coverage (factory
#          selection + Ollama HTTP) lives in test_summarizer_providers.py.
# Caller: pytest
# Callees: app.services.session_narrative, app.services.dwb_session (close_session,
#          generate_session_narrative), the /api/sessions + /api/projects endpoints
# Data In: per-test db_session + make_project fixture + monkeypatch-mocked LLM
# Data Out: assertions on parsed/persisted narrative, gate behavior, endpoint result
# Last Modified: 2026-06-25

"""DWBG-014 — session wrap-up summarizer, backend coverage. LLM call is mocked."""

import json
from datetime import datetime

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.services import dwb_session as svc
from app.services import session_narrative


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


def _open_session(db_session, project_id, method=DwbOpenMethod.regex):
    row = DwbSession(
        project_id=project_id, opened_at=_naive_now(), open_method=method,
    )
    db_session.add(row)
    db_session.flush()
    return row


_GOOD_NARRATIVE = {
    "lead": "Money-column precision sweep",
    "sections": [
        {"title": "What changed", "bullets": [
            "Widened money columns to decimal(17,6) in DataManipulation.php:21.",
        ]},
        {"title": "Caveat", "bullets": [
            "The diff was truncated; downstream consumers were not audited.",
        ]},
    ],
}


# ---------------------------------------------------------------------------
# Pure JSON parsing (_parse_narrative)
# ---------------------------------------------------------------------------


class TestParseNarrative:
    def test_parses_clean_json(self):
        out = session_narrative._parse_narrative(json.dumps(_GOOD_NARRATIVE))
        assert out["lead"] == "Money-column precision sweep"
        assert out["sections"][0]["title"] == "What changed"

    def test_strips_code_fence(self):
        fenced = "```json\n" + json.dumps(_GOOD_NARRATIVE) + "\n```"
        out = session_narrative._parse_narrative(fenced)
        assert out is not None
        assert out["lead"] == "Money-column precision sweep"

    def test_rejects_non_json(self):
        assert session_narrative._parse_narrative("not json at all") is None

    def test_rejects_missing_sections(self):
        assert session_narrative._parse_narrative('{"lead": "x"}') is None

    def test_drops_malformed_sections_keeps_good(self):
        raw = json.dumps({"lead": "x", "sections": [
            {"title": "ok", "bullets": ["a", "", 5]},
            {"title": "bad"},  # no bullets -> dropped
            "garbage",
        ]})
        out = session_narrative._parse_narrative(raw)
        assert len(out["sections"]) == 1
        assert out["sections"][0]["bullets"] == ["a"]

    def test_rejects_when_all_sections_empty(self):
        raw = json.dumps({"lead": "x", "sections": [{"title": "t", "bullets": []}]})
        assert session_narrative._parse_narrative(raw) is None


# ---------------------------------------------------------------------------
# generate_narrative best-effort behavior (DWBG-017: mocked at the PROVIDER seam)
#
# generate_narrative is now provider-agnostic: it builds the prompt, calls
# get_provider().complete(...), and parses. These tests mock the provider seam
# (a fake complete()) rather than the Anthropic SDK — that is the new contract
# point. Provider-internal skips (no key / SDK missing / backend down) are
# covered in test_summarizer_providers.py at the provider level.
# ---------------------------------------------------------------------------


class _FakeProvider:
    """A NarrativeProvider whose complete() returns a canned value (or raises)."""

    def __init__(self, *, text=None, boom=False):
        self._text = text
        self._boom = boom
        self.calls = []

    def complete(self, *, system, user, max_tokens):
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if self._boom:
            raise RuntimeError("boom")
        return self._text


class TestGenerateNarrative:
    def test_provider_returns_none_yields_none(self, monkeypatch):
        # Backend unavailable / no key / parse-fail all surface as complete()->None.
        provider = _FakeProvider(text=None)
        monkeypatch.setattr(session_narrative, "get_provider", lambda: provider)
        assert session_narrative.generate_narrative({"git": {}}) is None
        # The prompt was still built and passed through at the 8000-token ceiling.
        assert provider.calls and provider.calls[0]["max_tokens"] == 8000

    def test_provider_text_parses_into_narrative(self, monkeypatch):
        provider = _FakeProvider(text=json.dumps(_GOOD_NARRATIVE))
        monkeypatch.setattr(session_narrative, "get_provider", lambda: provider)
        out = session_narrative.generate_narrative({"git": {"commits": [1]}})
        assert out["lead"] == "Money-column precision sweep"

    def test_unparseable_provider_text_yields_none(self, monkeypatch):
        provider = _FakeProvider(text="not json at all")
        monkeypatch.setattr(session_narrative, "get_provider", lambda: provider)
        assert session_narrative.generate_narrative({"git": {}}) is None


# ---------------------------------------------------------------------------
# Auto-on-close wiring + force_session_writeup gate
# ---------------------------------------------------------------------------


class TestCloseWiringAndGate:
    def test_close_generates_narrative_when_gate_on(
        self, db_session, make_project, monkeypatch
    ):
        # Mock the summarizer's evidence + LLM so no git/API is touched.
        monkeypatch.setattr(
            svc, "build_work_record", lambda *a, **k: {"git": {"commits": [1]}}
        )
        monkeypatch.setattr(svc, "has_evidence", lambda rec: True)
        monkeypatch.setattr(svc, "generate_narrative", lambda rec: dict(_GOOD_NARRATIVE))

        proj = make_project(force_session_writeup=True)
        row = _open_session(db_session, proj["id"])
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        assert row.narrative is not None
        assert row.narrative_author == "summarizer"
        assert row.narrative_generated_at is not None
        # Deterministic summary baseline still present.
        assert row.summary is not None

    def test_close_skips_narrative_when_gate_off(
        self, db_session, make_project, monkeypatch
    ):
        called = {"n": 0}

        def _boom(*a, **k):
            called["n"] += 1
            return dict(_GOOD_NARRATIVE)

        monkeypatch.setattr(svc, "generate_narrative", _boom)
        proj = make_project(force_session_writeup=False)
        row = _open_session(db_session, proj["id"])
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        assert row.narrative is None
        assert called["n"] == 0  # summarizer never invoked when gate is off

    def test_tl_narrative_takes_precedence(
        self, db_session, make_project, monkeypatch
    ):
        called = {"n": 0}

        def _summarizer(*a, **k):
            called["n"] += 1
            return dict(_GOOD_NARRATIVE)

        monkeypatch.setattr(svc, "generate_narrative", _summarizer)
        proj = make_project(force_session_writeup=True)
        row = _open_session(db_session, proj["id"], method=DwbOpenMethod.ai_confident)
        tl_narrative = {"lead": "TL wrote this", "sections": [
            {"title": "Decisions", "bullets": ["chose A over B"]}]}
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
            headline="conscious close", narrative=tl_narrative,
        )
        # The TL narrative survives; the summarizer is not invoked.
        assert row.narrative_author == "tl"
        assert row.narrative["lead"] == "TL wrote this"
        assert called["n"] == 0

    def test_summarizer_failure_never_blocks_close(
        self, db_session, make_project, monkeypatch
    ):
        def _explode(*a, **k):
            raise RuntimeError("work record exploded")

        monkeypatch.setattr(svc, "build_work_record", _explode)
        proj = make_project(force_session_writeup=True)
        row = _open_session(db_session, proj["id"])
        # Must not raise; the close completes with stamps set, no narrative.
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        assert row.closed_at is not None
        assert row.narrative is None

    def test_redaction_applied_to_summarizer_narrative(
        self, db_session, make_project, monkeypatch
    ):
        leaky = {"lead": "leaked api_key=sk-SUMMARIZER1234567890abcd here",
                 "sections": [{"title": "t", "bullets": ["ok"]}]}
        monkeypatch.setattr(svc, "build_work_record", lambda *a, **k: {"git": {"commits": [1]}})
        monkeypatch.setattr(svc, "has_evidence", lambda rec: True)
        monkeypatch.setattr(svc, "generate_narrative", lambda rec: dict(leaky))
        proj = make_project(force_session_writeup=True)
        row = _open_session(db_session, proj["id"])
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        assert "sk-SUMMARIZER1234567890abcd" not in json.dumps(row.narrative)


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/generate-narrative endpoint
# ---------------------------------------------------------------------------


class TestGenerateNarrativeEndpoint:
    def test_404_for_missing_session(self, client):
        r = client.post("/api/sessions/999999/generate-narrative")
        assert r.status_code == 404

    def test_skip_returns_200_generated_false(
        self, client, db_session, make_project, monkeypatch
    ):
        # No evidence -> generate_session_narrative returns None -> generated False.
        monkeypatch.setattr(svc, "build_work_record", lambda *a, **k: {"git": {}})
        monkeypatch.setattr(svc, "has_evidence", lambda rec: False)
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        db_session.commit()
        r = client.post(f"/api/sessions/{row.id}/generate-narrative")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == row.id
        assert body["generated"] is False

    def test_success_persists_and_returns_narrative(
        self, client, db_session, make_project, monkeypatch
    ):
        monkeypatch.setattr(svc, "build_work_record", lambda *a, **k: {"git": {"commits": [1]}})
        monkeypatch.setattr(svc, "has_evidence", lambda rec: True)
        monkeypatch.setattr(svc, "generate_narrative", lambda rec: dict(_GOOD_NARRATIVE))
        proj = make_project()
        row = _open_session(db_session, proj["id"])
        db_session.commit()
        r = client.post(f"/api/sessions/{row.id}/generate-narrative")
        assert r.status_code == 200
        body = r.json()
        assert body["generated"] is True
        assert body["narrative_author"] == "summarizer"
        assert body["narrative"]["lead"] == "Money-column precision sweep"
