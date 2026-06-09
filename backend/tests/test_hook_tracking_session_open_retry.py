# Path: tests/test_hook_tracking_session_open_retry.py
# File: test_hook_tracking_session_open_retry.py
# Created: 2026-06-09
# Purpose: Tests for the DWB-343 Layer-1 OPEN-phrase retry inside handle_session_end
# Caller: pytest
# Callees: POST /api/hooks/session-end, app.services.hook_tracking.handle_session_end,
#          app.services.dwb_session.get_active_session, app.models.dwb_session.DwbSession
# Data In: factory fixtures (make_project), tmp_path-backed JSONL transcripts
# Data Out: Assertions on DwbSession rows opened/not opened post session-end
# Last Modified: 2026-06-09

"""DWB-343: Layer-1 OPEN regex retry on session-end events.

Background: Claude Code's SessionStart hook fires ~2 seconds BEFORE the user's
first message hits the transcript JSONL. The Layer-1 OPEN regex scan in
``handle_session_start`` therefore frequently runs against an empty/no-user-
message transcript and misses. By the time any Stop/SessionEnd/SubagentStop
hook fires, the transcript DOES contain the user's first message and the
regex catalogue can match.

These tests pin the retry behavior added to ``handle_session_end``:

  1. SessionEnd with transcript containing an open phrase + no active DWB
     session for the project -> opens via regex, open_method == "regex".
  2. SessionEnd with an already-open DWB session -> noop, no duplicate row
     (open_session returns the existing one).
  3. SessionEnd with a transcript missing any open phrase -> noop, no row
     created.
  4. SessionEnd with no transcript_path -> noop (existing guard inside
     ``try_open_dwb_session_from_transcript``).

The tests drive the public POST /api/hooks/session-end endpoint so the full
``handle_session_end`` path (token attribution, close-phrase scan, open
retry) runs end-to-end. DwbSession state is verified by direct ORM query
via the per-test db_session fixture.
"""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.dwb_session import DwbOpenMethod, DwbSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_user_transcript(tmp_path):
    """Factory that writes a Claude Code-shape JSONL transcript file.

    Each "message" in ``user_texts`` becomes a user turn line of the form::

        {"type": "user",
         "message": {"role": "user", "content": "<text>"},
         "timestamp": "..."}

    Pass ``[]`` (or omit) to write a transcript with no user lines (used to
    verify the no-match noop path).
    """
    _counter = [0]

    def _make(user_texts=None):
        _counter[0] += 1
        path = tmp_path / f"transcript_{_counter[0]}.jsonl"
        lines: list[str] = []
        for text in (user_texts or []):
            lines.append(
                json.dumps({
                    "type": "user",
                    "message": {"role": "user", "content": text},
                    "timestamp": "2026-06-09T17:19:37.663Z",
                })
            )
        path.write_text(("\n".join(lines) + "\n") if lines else "")
        return str(path)

    return _make


@pytest.fixture
def hook_project(make_project, tmp_path):
    """Project with a deterministic repo_path (used for cwd resolution)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return make_project(repo_path=str(repo))


def _session_id() -> str:
    return str(uuid.uuid4())


def _active_dwb_session_for(db_session, project_id) -> DwbSession | None:
    """Return the single open DwbSession for ``project_id``, or None.

    Direct ORM query rather than going through the service layer so this
    helper never hides a regression in ``get_active_session``.
    """
    return db_session.execute(
        select(DwbSession)
        .where(DwbSession.project_id == project_id)
        .where(DwbSession.closed_at.is_(None))
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSessionEndOpensViaRegexRetry:
    """DWB-343: handle_session_end runs the OPEN regex retry."""

    def test_opens_dwb_session_when_transcript_has_open_phrase(
        self, client, hook_project, make_user_transcript, db_session,
    ):
        """Case 1: SessionEnd with an open phrase + no active session.

        The retry inside ``handle_session_end`` must scan the transcript and
        open a DWB session via the regex catalogue (open_method=regex).
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]
        transcript = make_user_transcript(
            user_texts=["you are archie, read the playbook"],
        )

        # Pre-condition: no active DWB session.
        assert _active_dwb_session_for(db_session, pid) is None

        sid = _session_id()
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": repo,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ok"

        # Post-condition: exactly one open DwbSession exists for the project,
        # opened via regex, with the matched phrase recorded.
        active = _active_dwb_session_for(db_session, pid)
        assert active is not None, "expected a DWB session to be opened"
        assert active.open_method == DwbOpenMethod.regex
        assert active.open_phrase is not None
        assert "playbook" in active.open_phrase.lower()

    def test_noop_when_dwb_session_already_open(
        self, client, hook_project, make_user_transcript, db_session,
    ):
        """Case 2: SessionEnd with an open phrase BUT a session already open.

        open_session returns ``(None, existing)`` when a session is active,
        so the retry must be a silent no-op (no duplicate row, single-active
        invariant holds).
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        # Seed an already-open DWB session via the public open endpoint
        # (open_method=ai_confident so we can tell it apart from a regex open).
        from datetime import datetime, timezone
        opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        r0 = client.post("/api/sessions/open", json={
            "project_id": pid,
            "opened_at": opened_at,
            "open_method": "ai_confident",
            "open_phrase": "seeded by ai_confident",
        })
        assert r0.status_code == 201, r0.text
        seeded_id = r0.json()["id"]

        transcript = make_user_transcript(
            user_texts=["you are archie, read the playbook"],
        )
        sid = _session_id()
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": repo,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        # The seeded session must still be the only open row; the retry
        # observed it as existing and noop'd. open_method stays ai_confident.
        db_session.expire_all()
        rows = db_session.execute(
            select(DwbSession)
            .where(DwbSession.project_id == pid)
            .where(DwbSession.closed_at.is_(None))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == seeded_id
        assert rows[0].open_method == DwbOpenMethod.ai_confident

    def test_noop_when_transcript_has_no_open_phrase(
        self, client, hook_project, make_user_transcript, db_session,
    ):
        """Case 3: SessionEnd with a transcript that does not match OPEN_PATTERNS.

        Nothing in the user text triggers the regex; no DwbSession row
        should be created.
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]
        transcript = make_user_transcript(
            user_texts=[
                "hello there",
                "can you bump the ticket to in_progress",
                "what's the status",
            ],
        )

        sid = _session_id()
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": repo,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        # No DwbSession at all (neither open nor closed) should exist.
        rows = db_session.execute(
            select(DwbSession).where(DwbSession.project_id == pid)
        ).scalars().all()
        assert rows == []

    def test_noop_when_transcript_path_missing(
        self, client, hook_project, db_session,
    ):
        """Case 4: SessionEnd payload omits transcript_path.

        ``try_open_dwb_session_from_transcript`` guards with an early return
        when transcript_path is falsy. The endpoint must still 200 and no
        DwbSession row should be created.
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        sid = _session_id()
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": repo,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        rows = db_session.execute(
            select(DwbSession).where(DwbSession.project_id == pid)
        ).scalars().all()
        assert rows == []
