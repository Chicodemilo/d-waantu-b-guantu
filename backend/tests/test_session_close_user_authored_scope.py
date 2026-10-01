# Path: tests/test_session_close_user_authored_scope.py
# File: test_session_close_user_authored_scope.py
# Created: 2026-06-22
# Purpose: DWB-414 - session phrase detection must fire only on genuine
#          user-authored turns; quoted/example/synthetic text must not open
#          or close a DWB session.
# Caller: pytest
# Callees: app.services.hook_tracking._extract_user_message_texts,
#          _is_synthetic_user_text, _is_human_authored_entry,
#          try_close_dwb_session_from_transcript,
#          POST /api/hooks/session-end, POST /api/hooks/user-prompt
# Data In: factory fixtures (make_project), tmp_path-backed JSONL transcripts
# Data Out: Assertions on extracted texts + DwbSession open/closed state
# Last Modified: 2026-09-29 (DWB-592: provenance allowlist, prose relay coverage)

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
    _is_human_authored_entry,
    _is_synthetic_user_text,
)


# DWB-592: the prose relay wrapper, derived from the shape Claude Code
# currently writes into transcripts rather than from anyone's idea of it: a
# single line ending in a colon, with the relayed body starting on the very
# next line and no blank line between. The wrapper line is harness text. The
# body below is written here, by hand, on purpose: those turns quote the human
# and user-authored text is never persisted (DWB-351), so no transcript
# content appears in this file, the ticket, or any comment.
RELAY_PROSE_PREFIX = "Another Claude session sent a message:"


def _relay_prose(body):
    return f"{RELAY_PROSE_PREFIX}\n{body}"


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


@pytest.fixture
def warnings_from_scan(monkeypatch):
    """Warnings the scan emitted, captured WITHOUT touching global logging.

    This deliberately does not use ``caplog``. Barry saw the all-synthetic
    case go red under a full suite and green in isolation, which is the shape
    of a test that depends on global logging state another test can disturb
    (propagation flags, handler levels, logging.disable). Patching the
    module's own logger removes that dependency entirely: the assertion is on
    what this function called, not on where a record happened to end up.
    """
    from app.services import hook_tracking

    captured: list[str] = []

    class _Recorder:
        def warning(self, msg, *args, **kwargs):
            captured.append(msg % args if args else msg)

        def __getattr__(self, name):
            # Everything else on the module logger stays a no-op so an
            # unrelated info/exception call cannot fail the test.
            return lambda *a, **k: None

    monkeypatch.setattr(hook_tracking, "logger", _Recorder())
    return captured


def _user_str(text, *, prompt_source="typed"):
    """A genuine human user turn.

    DWB-592: this helper used to omit ``promptSource`` entirely, which is the
    very defect this ticket exists to fix sitting in the tests that were meant
    to catch it: a fixture written from an idea of the format rather than the
    format. Claude Code stamps every turn the human actually submits, and the
    extractor now requires that stamp, so a fixture without one is not a
    genuine turn - it is a relay wearing one's clothes.

    ``prompt_source=None`` builds the un-stamped shape deliberately, for the
    cases that assert harness-injected turns are excluded.
    """
    entry = {
        "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": "2026-06-22T12:00:00.000Z",
    }
    if prompt_source is not None:
        entry["promptSource"] = prompt_source
        entry["origin"] = {"kind": "human"}
    return entry


def _teammate_msg(text):
    """A teammate-message relay in the ANGLE-TAG shape (harness-injected, so
    no promptSource stamp)."""
    return _user_str(
        f'<teammate-message teammate_id="team-lead">\n{text}\n</teammate-message>',
        prompt_source=None,
    )


def _relay_prose_msg(text):
    """A teammate-message relay in the PROSE shape: the dominant one, and the
    one the pre-DWB-592 prefix test could not see."""
    return _user_str(_relay_prose(text), prompt_source=None)


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
    e = _user_str(text, prompt_source=None)
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
# DWB-592: provenance allowlist
#
# The defect: _is_synthetic_user_text was startswith over sixteen angle-bracket
# literals, so a relay opening with PROSE could not match and was classified as
# human-typed. That shape outnumbered the caught one by about ten to one.
#
# WHICH OF THESE CASES BITE. Everything under TestProseRelayIsNotHumanAuthored
# names the defect and goes red if the allowlist is removed. TestNoOverCatch
# guards the opposite risk, a filter widened until it swallows real input; its
# cases pass under the old implementation too and are NOT evidence the fix is
# present. TestUnseenWrapperFailsClosed is the design claim: it is built so the
# discarded implementation could not satisfy it, because the wording it uses
# appears on no list anywhere.
# ---------------------------------------------------------------------------


class TestProseRelayIsNotHumanAuthored:
    """AC1: the prose relay shape is classified synthetic."""

    def test_prose_relay_entry_is_not_human_authored(self):
        entry = _relay_prose_msg("shut it down for the night")
        assert _is_human_authored_entry(entry) is False

    def test_prose_relay_is_excluded_from_the_scan(self, write_transcript):
        path = write_transcript([_relay_prose_msg("shut it down for the night")])
        assert _extract_user_message_texts(path, head=False) == []

    def test_prose_relay_quoting_a_close_phrase_does_not_close(
        self, client, db_session, hook_project, write_transcript
    ):
        pid = hook_project["id"]
        _seed_open_session(client, pid)
        path = write_transcript([_relay_prose_msg("shut it down for the night")])
        r = client.post("/api/hooks/session-end", json={
            "session_id": _session_id(),
            "transcript_path": path,
            "cwd": hook_project["repo_path"],
            "hook_event_name": "SessionEnd",
        })
        assert r.status_code == 200, r.text
        db_session.expire_all()
        assert _active(db_session, pid) is not None

    def test_the_old_prefix_test_could_not_have_caught_it(self):
        """Pins WHY this needed a new mechanism: the prose shape does not start
        with an angle bracket, so no prefix test over tag literals can see it.
        If this ever goes red the relay format has changed and the numbers in
        the ticket no longer describe reality."""
        assert not RELAY_PROSE_PREFIX.startswith("<")
        assert _is_synthetic_user_text(_relay_prose("anything")) is False


class TestUnseenWrapperFailsClosed:
    """AC4, the design claim: an unseen wrapper wording is synthetic by
    default. Driven with wording that is on no list, so the discarded
    implementation could not satisfy these by construction."""

    @pytest.mark.parametrize("text", [
        "Relayed from the mesh: shut it down for the night",
        "Forwarded by the scheduler. shut it down for the night",
        "[[inbox]] shut it down for the night",
    ])
    def test_unknown_prose_wrapper_without_provenance_is_synthetic(self, text):
        assert _is_human_authored_entry(_user_str(text, prompt_source=None)) is False

    def test_unknown_angle_wrapper_is_caught_by_shape_too(self):
        # Belt and braces for the text-only call site: a kebab-case tag nobody
        # has enumerated still reads as a wrapper.
        assert _is_synthetic_user_text("<mesh-relay from='x'>close it</mesh-relay>") is True

    def test_an_unrecognised_provenance_value_is_not_human(self):
        # If CC adds a new source, it is not human until we say so.
        assert _is_human_authored_entry(
            _user_str("shut it down for the night", prompt_source="replayed")
        ) is False


class TestNoOverCatch:
    """AC3. Widening a filter until it swallows real input trades a silent
    failure for a louder one.

    BE PRECISE ABOUT WHAT THESE PROVE. They all pass under the OLD
    implementation, so they are NOT evidence the provenance allowlist exists.
    But they are not idle either: they go red against the naive fix this
    ticket forbids. Adding the prose wording to the text filter makes
    test_human_typing_the_relay_wording_is_still_human fail, because a human
    who types that sentence loses control of their own session. That is the
    case this class is here to catch."""

    def test_human_typing_the_relay_wording_is_still_human(self):
        # The adversarial case. It passes BY CONSTRUCTION: provenance decides,
        # so no wording a human can type changes the verdict.
        entry = _user_str(_relay_prose("shut it down for the night"))
        assert _is_human_authored_entry(entry) is True

    def test_human_sentence_merely_starting_with_another_is_human(self):
        assert _is_human_authored_entry(
            _user_str("Another thing before we stop: shut it down for the night")
        ) is True

    def test_queued_prompts_are_human(self):
        assert _is_human_authored_entry(
            _user_str("shut it down for the night", prompt_source="queued")
        ) is True

    def test_human_typed_markup_is_not_mistaken_for_a_wrapper(self):
        # <div> and <3 have no hyphen, so the kebab-case shape leaves them be.
        assert _is_synthetic_user_text("<div>what does this render as</div>") is False
        assert _is_synthetic_user_text("<3 that idea") is False

    def test_a_human_close_phrase_still_closes(
        self, client, db_session, hook_project, write_transcript
    ):
        pid = hook_project["id"]
        _seed_open_session(client, pid)
        path = write_transcript([_user_str("shut it down for the night")])
        r = client.post("/api/hooks/session-end", json={
            "session_id": _session_id(),
            "transcript_path": path,
            "cwd": hook_project["repo_path"],
            "hook_event_name": "SessionEnd",
        })
        assert r.status_code == 200, r.text
        db_session.expire_all()
        assert _active(db_session, pid) is None


class TestDegradationIsLoud:
    """The cost of failing closed: if provenance ever stops arriving, phrase
    detection stops rather than misfires. That must not be silent, because
    silence is how the mis-classified turns accumulated unseen."""

    def test_transcript_of_only_synthetic_turns_warns(
        self, write_transcript, warnings_from_scan
    ):
        path = write_transcript([
            _relay_prose_msg("shut it down for the night"),
            _teammate_msg("and again"),
        ])
        assert _extract_user_message_texts(path, head=False) == []
        assert any("none human-authored" in w for w in warnings_from_scan)

    def test_no_warning_when_a_human_turn_is_present(
        self, write_transcript, warnings_from_scan
    ):
        path = write_transcript([
            _relay_prose_msg("shut it down for the night"),
            _user_str("ship it"),
        ])
        assert _extract_user_message_texts(path, head=False) == ["ship it"]
        assert not any("none human-authored" in w for w in warnings_from_scan)

    def test_no_warning_on_an_empty_transcript(
        self, write_transcript, warnings_from_scan
    ):
        path = write_transcript([])
        assert _extract_user_message_texts(path, head=False) == []
        assert not any("none human-authored" in w for w in warnings_from_scan)


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
