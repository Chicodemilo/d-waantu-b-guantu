# Path: tests/test_session_close_user_authored_scope.py
# File: test_session_close_user_authored_scope.py
# Created: 2026-06-22
# Purpose: DWB-414 - session phrase detection must fire only on genuine
#          user-authored turns; quoted/example/synthetic text must not open
#          or close a DWB session.
# Caller: pytest
# Callees: app.services.hook_tracking._extract_user_message_texts,
#          _is_synthetic_user_text, try_close_dwb_session_from_transcript,
#          POST /api/hooks/session-end, POST /api/hooks/user-prompt
# Data In: factory fixtures (make_project), tmp_path-backed JSONL transcripts
# Data Out: Assertions on extracted texts + DwbSession open/closed state
# Last Modified: 2026-06-22

"""DWB-414: scope session open/close phrase detection to user-authored turns.

Background (DWB-396): the Layer-1 transcript close-scan matched close phrases
that appeared in NON-human text. Claude Code records tool results, teammate-
message relays, slash-command echoes + stdout, task notifications, injected
system reminders, and meta entries all with role/type "user". A close phrase
quoted or exampled inside any of those (e.g. a teammate relaying "...then say
shut it down for the night", or this very ticket's prose surfacing in a tool
result) falsely closed the active session.

The fix tightens ``_extract_user_message_texts`` to return only genuine human
turns, and guards the UserPromptSubmit fast path against a synthetic-wrapped
prompt. These tests pin both:

  1. Unit: synthetic user-role entries are dropped; genuine prose survives.
  2. Integration (transcript close-scan): a close phrase that exists ONLY in
     synthetic content does NOT close; a genuine human close phrase DOES.
  3. Integration (UserPromptSubmit): a synthetic-wrapped prompt noops; a
     genuine prompt closes.

Privacy (DWB-351): the scan matches in-memory and persists only the catalogued
phrase substring, never the user's literal text. Nothing here asserts that we
store raw prompt text, because we must not.
"""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.dwb_session import DwbCloseMethod, DwbSession
from app.services.hook_tracking import (
    _extract_user_message_texts,
    _is_synthetic_user_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def write_transcript(tmp_path):
    """Write raw JSONL entries (arbitrary dicts) and return the file path.

    Unlike the open-retry test's helper, this takes full entry dicts so a
    test can construct tool-result / teammate-message / meta shapes exactly
    as Claude Code records them.
    """
    _counter = [0]

    def _make(entries):
        _counter[0] += 1
        path = tmp_path / f"transcript_{_counter[0]}.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return str(path)

    return _make


def _user_str(text):
    """A genuine human user turn: string content, no synthetic markers."""
    return {
        "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": "2026-06-22T12:00:00.000Z",
    }


def _teammate_msg(text):
    """A teammate-message relay (role=user, harness-injected)."""
    return _user_str(f'<teammate-message teammate_id="team-lead">\n{text}\n</teammate-message>')


def _tool_result(text):
    """A tool-result echo (role=user, toolUseResult present, list content)."""
    return {
        "type": "user",
        "toolUseResult": {"stdout": text},
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": text, "tool_use_id": "t1"}],
        },
        "timestamp": "2026-06-22T12:00:01.000Z",
    }


def _meta(text):
    """A meta entry (isMeta True, role=user)."""
    e = _user_str(text)
    e["isMeta"] = True
    return e


@pytest.fixture
def hook_project(make_project, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return make_project(repo_path=str(repo))


def _session_id():
    return str(uuid.uuid4())


def _active(db_session, project_id):
    return db_session.execute(
        select(DwbSession)
        .where(DwbSession.project_id == project_id)
        .where(DwbSession.closed_at.is_(None))
    ).scalar_one_or_none()


def _seed_open_session(client, pid):
    """Seed an active session via the public open endpoint (ai_confident so a
    regex close is distinguishable from the seed)."""
    from datetime import datetime, timezone

    opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    r = client.post("/api/sessions/open", json={
        "project_id": pid,
        "opened_at": opened_at,
        "open_method": "ai_confident",
        "open_phrase": "seeded",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Unit: _is_synthetic_user_text
# ---------------------------------------------------------------------------


class TestIsSyntheticUserText:
    def test_genuine_prose_is_not_synthetic(self):
        assert _is_synthetic_user_text("shut it down for the night") is False
        assert _is_synthetic_user_text("close the session please") is False

    @pytest.mark.parametrize("text", [
        '<teammate-message teammate_id="Barry">close the session</teammate-message>',
        "<command-name>dwb-close</command-name>",
        "<local-command-stdout>shut it down for the night</local-command-stdout>",
        "<task-notification>done; that's a wrap</task-notification>",
        "<system-reminder>close this session</system-reminder>",
        "<user-prompt-submit-hook>end of session</user-prompt-submit-hook>",
        "  <teammate-message>leading whitespace still synthetic</teammate-message>",
    ])
    def test_synthetic_wrappers_detected(self, text):
        assert _is_synthetic_user_text(text) is True


# ---------------------------------------------------------------------------
# Unit: _extract_user_message_texts scoping
# ---------------------------------------------------------------------------


class TestExtractUserMessageTextsScoping:
    def test_genuine_text_is_returned(self, write_transcript):
        path = write_transcript([_user_str("hello there"), _user_str("ship it")])
        texts = _extract_user_message_texts(path, head=True)
        assert texts == ["hello there", "ship it"]

    def test_teammate_message_excluded(self, write_transcript):
        path = write_transcript([_teammate_msg("shut it down for the night")])
        assert _extract_user_message_texts(path, head=False) == []

    def test_tool_result_excluded(self, write_transcript):
        path = write_transcript([_tool_result("close the session")])
        assert _extract_user_message_texts(path, head=False) == []

    def test_meta_entry_excluded(self, write_transcript):
        path = write_transcript([_meta("that's a wrap")])
        assert _extract_user_message_texts(path, head=False) == []

    def test_mixed_returns_only_genuine(self, write_transcript):
        path = write_transcript([
            _user_str("can you look at the bug"),
            _teammate_msg("shut it down for the night"),
            _tool_result("close the session"),
            _meta("end of session"),
            _user_str("thanks"),
        ])
        texts = _extract_user_message_texts(path, head=True)
        assert texts == ["can you look at the bug", "thanks"]


# ---------------------------------------------------------------------------
# Integration: transcript close-scan
# ---------------------------------------------------------------------------


class TestCloseScanIgnoresSyntheticTurns:
    def test_quoted_close_phrase_in_synthetic_text_does_not_close(
        self, client, hook_project, write_transcript, db_session,
    ):
        """The headline DWB-414 case: a close phrase present ONLY in synthetic
        (non-human) content must not close the active session."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]
        seeded = _seed_open_session(client, pid)

        # Genuine human turns carry NO close phrase; the only close phrase
        # lives in a teammate relay + a tool result + a meta entry.
        transcript = write_transcript([
            _user_str("here is the spec for the close-scan fix"),
            _teammate_msg("when you are done, the user might say shut it down for the night"),
            _tool_result("example: 'close the session' should be quoted text"),
            _meta("that's a wrap"),
            _user_str("looks good, keep going"),
        ])

        r = client.post("/api/hooks/session-end", json={
            "session_id": _session_id(),
            "cwd": repo,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        db_session.expire_all()
        active = _active(db_session, pid)
        assert active is not None, "session was falsely closed by synthetic text"
        assert active.id == seeded

    def test_genuine_close_phrase_closes(
        self, client, hook_project, write_transcript, db_session,
    ):
        """Control: a genuine human close phrase still closes via regex."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]
        _seed_open_session(client, pid)

        transcript = write_transcript([
            _user_str("great work today"),
            _user_str("shut it down for the night"),
        ])

        r = client.post("/api/hooks/session-end", json={
            "session_id": _session_id(),
            "cwd": repo,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        db_session.expire_all()
        assert _active(db_session, pid) is None, "genuine close phrase failed to close"
        closed = db_session.execute(
            select(DwbSession).where(DwbSession.project_id == pid)
        ).scalars().all()
        assert len(closed) == 1
        assert closed[0].close_method == DwbCloseMethod.regex


# ---------------------------------------------------------------------------
# Integration: UserPromptSubmit fast path
# ---------------------------------------------------------------------------


class TestUserPromptSyntheticScope:
    def test_synthetic_wrapped_prompt_does_not_close(
        self, client, hook_project, db_session,
    ):
        pid = hook_project["id"]
        repo = hook_project["repo_path"]
        seeded = _seed_open_session(client, pid)

        r = client.post("/api/hooks/user-prompt", json={
            "session_id": _session_id(),
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
            "prompt": '<teammate-message teammate_id="Barry">shut it down for the night</teammate-message>',
        })
        assert r.status_code == 200, r.text
        assert r.json()["reason"] == "synthetic_prompt"

        db_session.expire_all()
        active = _active(db_session, pid)
        assert active is not None and active.id == seeded

    def test_genuine_prompt_closes(
        self, client, hook_project, db_session,
    ):
        pid = hook_project["id"]
        repo = hook_project["repo_path"]
        _seed_open_session(client, pid)

        r = client.post("/api/hooks/user-prompt", json={
            "session_id": _session_id(),
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "ok, shut it down for the night",
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "closed"

        db_session.expire_all()
        assert _active(db_session, pid) is None
