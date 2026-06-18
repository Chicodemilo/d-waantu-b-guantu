# Path: tests/test_hook_session_dwb_link.py
# File: test_hook_session_dwb_link.py
# Created: 2026-06-12
# Purpose: Tests for DWB-373 A2 - HookSession.dwb_session_id linker
# Caller: pytest
# Callees: POST /api/hooks/session-start, POST /api/hooks/session-end,
#          POST /api/sessions/open, app.services.hook_tracking,
#          app.models.hook_session.HookSession
# Data In: factory fixtures (make_project), tmp_path repo dirs
# Data Out: Assertions on HookSession.dwb_session_id population
# Last Modified: 2026-06-12

"""DWB-373: HookSession.dwb_session_id linker.

The model column existed since DWB-335 with a docstring promising "future
ingestion sets this when an open DWB session is found at hook receipt time."
That ingestion never happened in production, so _rollup_tokens (which sums
hook_sessions filtered by dwb_session_id == session.id) summed an empty set
and reported total_tokens=0 for every DWB session row in the list endpoint.

These tests pin the linker behavior added across three HookSession insert
sites + two update branches:

  1. handle_session_start with no active DWB session -> dwb_session_id=None.
  2. handle_session_start with an active DWB session -> stamped at insert.
  3. handle_session_end (create-on-end path) with active DWB session ->
     stamped at create.
  4. handle_session_end (update-existing path) with NULL dwb_session_id ->
     backfilled to the now-active session.
  5. handle_session_end (update-existing path) with non-NULL dwb_session_id
     -> preserved (never reattributed).
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.hook_session import HookSession


@pytest.fixture
def make_user_transcript(tmp_path):
    """Minimal JSONL transcript factory used by the SessionEnd path."""
    _counter = [0]

    def _make(user_texts=None):
        _counter[0] += 1
        path = tmp_path / f"transcript_{_counter[0]}.jsonl"
        lines: list[str] = []
        for text in (user_texts or []):
            lines.append(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": text},
                "timestamp": "2026-06-12T13:30:00.000Z",
            }))
        path.write_text(("\n".join(lines) + "\n") if lines else "")
        return str(path)

    return _make


@pytest.fixture
def hook_project(make_project, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return make_project(repo_path=str(repo))


def _seed_open_dwb_session(client, project_id: int) -> int:
    """Open a DWB session via the public endpoint, return its id."""
    opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    r = client.post("/api/sessions/open", json={
        "project_id": project_id,
        "opened_at": opened_at,
        "open_method": "ai_confident",
        "open_phrase": "test seed",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _hook_session(db_session, session_id: str) -> HookSession | None:
    db_session.expire_all()
    return db_session.execute(
        select(HookSession).where(HookSession.session_id == session_id)
    ).scalar_one_or_none()


class TestSessionStartLinker:
    def test_no_active_dwb_session_leaves_link_null(
        self, client, hook_project, db_session,
    ):
        sid = str(uuid.uuid4())
        r = client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "hook_event": "SessionStart",
        })
        assert r.status_code == 200, r.text

        hs = _hook_session(db_session, sid)
        assert hs is not None
        assert hs.dwb_session_id is None

    def test_active_dwb_session_stamps_link_at_start(
        self, client, hook_project, db_session,
    ):
        dwb_id = _seed_open_dwb_session(client, hook_project["id"])

        sid = str(uuid.uuid4())
        r = client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "hook_event": "SessionStart",
        })
        assert r.status_code == 200, r.text

        hs = _hook_session(db_session, sid)
        assert hs is not None
        assert hs.dwb_session_id == dwb_id


class TestSessionEndLinker:
    def test_create_on_end_path_stamps_link(
        self, client, hook_project, make_user_transcript, db_session,
    ):
        dwb_id = _seed_open_dwb_session(client, hook_project["id"])

        # SessionEnd with no prior start: handle_session_end creates the row.
        sid = str(uuid.uuid4())
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "transcript_path": make_user_transcript([]),
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        hs = _hook_session(db_session, sid)
        assert hs is not None
        assert hs.dwb_session_id == dwb_id

    def test_update_path_backfills_when_link_is_null(
        self, client, hook_project, make_user_transcript, db_session,
    ):
        # Start a hook session BEFORE any DWB session opens.
        sid = str(uuid.uuid4())
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "hook_event": "SessionStart",
        })
        hs = _hook_session(db_session, sid)
        assert hs.dwb_session_id is None

        # Now open a DWB session, then fire SessionEnd. The update branch
        # should backfill dwb_session_id since it was NULL.
        dwb_id = _seed_open_dwb_session(client, hook_project["id"])
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "transcript_path": make_user_transcript([]),
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        hs = _hook_session(db_session, sid)
        assert hs.dwb_session_id == dwb_id

    def test_update_path_preserves_existing_link(
        self, client, hook_project, make_user_transcript, db_session,
    ):
        # Open a DWB session first, then start a hook session inside it.
        first_dwb = _seed_open_dwb_session(client, hook_project["id"])
        sid = str(uuid.uuid4())
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "hook_event": "SessionStart",
        })
        hs = _hook_session(db_session, sid)
        assert hs.dwb_session_id == first_dwb

        # Close the first DWB session, open a second. The hook session is
        # in-flight across the boundary; on SessionEnd it must NOT reattribute
        # to the newer DWB session - the historical link is preserved.
        client.post(f"/api/sessions/{first_dwb}/close", json={
            "close_method": "ai_confident",
            "close_reason": "explicit",
            "close_phrase": "done",
            "headline": "hook session link test close",
        })
        second_dwb = _seed_open_dwb_session(client, hook_project["id"])

        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": hook_project["repo_path"],
            "transcript_path": make_user_transcript([]),
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200, r.text

        hs = _hook_session(db_session, sid)
        assert hs.dwb_session_id == first_dwb
        assert hs.dwb_session_id != second_dwb
