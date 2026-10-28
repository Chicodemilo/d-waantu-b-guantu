# Path: tests/test_dwb_session_reopen_loop_dwb682.py
# File: test_dwb_session_reopen_loop_dwb682.py
# Created: 2026-10-28
# Purpose: DWB-682 - a transcript entry opens exactly one DWB session, ever
# Caller: pytest
# Callees: POST /api/hooks/session-start, POST /api/hooks/session-end,
#          app.services.hook_tracking.try_open_dwb_session_from_transcript,
#          app.services.hook_tracking._transcript_entry_key
# Data In: factory fixtures (make_project), tmp_path-backed JSONL transcripts
# Data Out: Assertions on the NUMBER of DwbSession rows across a close sequence
# Last Modified: 2026-10-28

"""DWB-682: closing a session opened another, so HANDOFF could record a lie.

THE DEFECT. ``try_open_dwb_session_from_transcript`` scans the HEAD of the
transcript - the first 50 human-authored turns. The open phrase a human typed
at 11:13 therefore matched on every scan for the rest of the day. The scan runs
on SessionStart AND on every SessionEnd / Stop / SubagentStop (the DWB-343
retry), and ``handle_session_end`` runs the close scan and the open scan back
to back, so a single hook event closed a session and opened the next one. Four
closes were needed to reach an empty open set on the reporting project, and a
team lead wrote "all sessions closed" into HANDOFF.md while one was open.

The already-open no-op never helped: the dangerous moment is immediately AFTER
a close, when the window is genuinely empty and the scan is entitled to open.

WHAT THESE TESTS ASSERT, AND WHY IT IS A ROW COUNT RATHER THAN AN OPEN SET.

The acceptance is "no reachable sequence of closes plus ordinary shutdown
traffic leaves a NEW session open". It is deliberately not "the open set ends
up empty", because DWB-395 would fail that forever and correctly: a `regex`
close is low-precision, so hook activity within
``_GRACE_RESURRECT_SECONDS`` RESURRECTS that same row rather than opening
another. That is a designed feature with a human-in-the-loop exemption list
(slash / ai_confident / ai_asked / idle_timeout are never resurrected), and it
is out of scope here.

The two are easy to confuse from the outside and the distinction is the whole
point of this file: DWB-682 MINTS A NEW ROW from a spent phrase, DWB-395
UN-CLOSES AN EXISTING ONE. So every assertion below counts rows.

ONE EXISTING TEST READS AS COVERAGE AND IS NOT.
``test_hook_tracking_session_open_retry.py::
TestSessionEndOpensViaRegexRetry::test_noop_when_dwb_session_already_open``
pins the already-open guard. That guard is precisely the one that does NOT
help here, because it only suppresses a scan while a session is open. Nobody
should read it as covering the reopen loop.

A NOTE ON THE INSTRUMENT. An earlier hand-probe of this sequence reported a
clean "no defect" while the code under test had never executed: the hook
handlers return early on a session_id they have already seen, so reusing one
across rounds meant the scan was never reached. Every hook call below gets a
fresh session_id for that reason, and the first assertion of the walk is that
a session was opened at all - a walk over an empty set terminates trivially
and proves nothing.
"""

import ast
import json
import uuid as uuidlib
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.dwb_session import DwbCloseMethod, DwbSession
from app.services.hook_tracking import _transcript_entry_key


OPEN_PHRASE = "you are archie, read your playbook"
CLOSE_PHRASE = "close the session"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transcript(tmp_path):
    """A Claude Code-shape JSONL transcript that can be APPENDED to, the way a
    real one grows during a session.

    Entries carry ``uuid`` and ``promptSource`` because the real harness stamps
    both: ``promptSource`` is what ``_is_human_authored_entry`` allowlists on
    (DWB-592), and ``uuid`` is the per-entry identity DWB-682 keys on. Measured
    across 40 real transcripts on the development machine, 1555 of 1555
    human-authored turns carried a uuid and no file repeated one.
    """
    class _Transcript:
        def __init__(self, path: Path):
            self.path = path
            path.write_text("")

        def __str__(self):
            return str(self.path)

        def user(self, text, *, entry_uuid=None):
            entry = {
                "type": "user",
                "message": {"role": "user", "content": text},
                "promptSource": "typed",
                "timestamp": "2026-10-28T11:13:30.123Z",
            }
            if entry_uuid is not None:
                entry["uuid"] = entry_uuid
            with self.path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
            return entry_uuid

        def assistant(self):
            with self.path.open("a") as fh:
                fh.write(json.dumps({
                    "type": "assistant",
                    "timestamp": "2026-10-28T11:13:35.000Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "ok"}],
                        "usage": {
                            "input_tokens": 10, "output_tokens": 5,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                    },
                }) + "\n")

    return _Transcript(tmp_path / "transcript.jsonl")


@pytest.fixture
def hook_project(make_project, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return make_project(repo_path=str(repo))


def _rows(db_session, project_id):
    """Every DwbSession row for the project, oldest first. A COUNT of these is
    the measurement; the open/closed split is DWB-395's business, not ours."""
    return list(db_session.execute(
        select(DwbSession)
        .where(DwbSession.project_id == project_id)
        .order_by(DwbSession.id)
    ).scalars().all())


def _hook(client, event, *, project, transcript_path, session_id=None):
    """Fire one hook with a session_id nothing has seen before.

    A reused id short-circuits on the idempotent / already-completed guards
    BEFORE the transcript scan runs, which makes the whole sequence a no-op
    that reads as a pass.
    """
    sid = session_id or str(uuidlib.uuid4())
    route = "session-start" if event == "SessionStart" else "session-end"
    resp = client.post(f"/api/hooks/{route}", json={
        "session_id": sid,
        "transcript_path": str(transcript_path),
        "cwd": project["repo_path"],
        "hook_event_name": event,
    })
    assert resp.status_code == 200, resp.text
    return sid


# ---------------------------------------------------------------------------
# The sequence walk
# ---------------------------------------------------------------------------


class TestSpentPhraseNeverOpensASecondSession:

    def test_close_then_ordinary_shutdown_traffic_mints_no_new_session(
        self, client, hook_project, transcript, db_session
    ):
        """THE ACCEPTANCE TEST. A sequence, not a single close.

        Pre-fix this grew one row per round without bound. The reporting
        project needed four closes to reach an empty open set and would have
        needed a fifth.
        """
        transcript.user(OPEN_PHRASE, entry_uuid="u-open-morning")
        transcript.assistant()

        _hook(client, "SessionStart", project=hook_project,
              transcript_path=transcript)

        opened = _rows(db_session, hook_project["id"])
        # POSITIVE CONTROL, FIRST. A walk over an empty set terminates
        # trivially; without this the rest of the test passes when the scan
        # never ran at all.
        assert len(opened) == 1, (
            "no session was opened, so the sequence below would prove nothing"
        )
        assert opened[0].open_transcript_key == "u-open-morning"

        # The human types the close phrase; it lands at the TAIL.
        transcript.user(CLOSE_PHRASE, entry_uuid="u-close-evening")
        transcript.assistant()

        # The close event itself: handle_session_end runs the close scan and
        # then the open retry, in that order, in one call. This is where the
        # defect was sharpest.
        _hook(client, "SessionEnd", project=hook_project,
              transcript_path=transcript)
        assert len(_rows(db_session, hook_project["id"])) == 1, (
            "the close event re-opened from the same spent phrase"
        )

        # Ordinary teammate shutdown traffic, round after round. Each is a
        # Claude Code session the hooks have never seen.
        for round_number in range(1, 6):
            _hook(client, "SessionStart", project=hook_project,
                  transcript_path=transcript)
            _hook(client, "SubagentStop", project=hook_project,
                  transcript_path=transcript)
            assert len(_rows(db_session, hook_project["id"])) == 1, (
                f"a new session was minted on round {round_number}; "
                "the spent phrase is opening sessions again"
            )

    def test_a_phrase_typed_again_does_open_a_second_session(
        self, client, hook_project, transcript, db_session
    ):
        """The guard must not be a blanket refusal.

        This is the case that forces a PER-ENTRY key rather than a
        per-transcript flag: the same words, typed again, are a new intent and
        must open a new session.
        """
        transcript.user(OPEN_PHRASE, entry_uuid="u-open-morning")
        transcript.assistant()
        _hook(client, "SessionStart", project=hook_project,
              transcript_path=transcript)

        transcript.user(CLOSE_PHRASE, entry_uuid="u-close-midday")
        transcript.assistant()
        _hook(client, "SessionEnd", project=hook_project,
              transcript_path=transcript)

        before = _rows(db_session, hook_project["id"])
        assert len(before) == 1
        assert before[0].closed_at is not None, "the close phrase did not close"

        # Restamp the close as `slash`, a method DWB-395 never resurrects, so
        # the next hook finds a genuinely empty window. Otherwise the regex
        # close would be un-closed inside the grace window and this test would
        # be measuring DWB-395 instead of the DWB-682 guard.
        before[0].close_method = DwbCloseMethod.slash
        db_session.flush()

        # The human types it again — a NEW entry, so a new uuid.
        transcript.user(OPEN_PHRASE, entry_uuid="u-open-evening")
        transcript.assistant()
        _hook(client, "SessionStart", project=hook_project,
              transcript_path=transcript)

        after = _rows(db_session, hook_project["id"])
        assert len(after) == 2, (
            "a freshly typed open phrase was refused; the guard is too wide"
        )
        assert after[1].open_transcript_key == "u-open-evening"


# ---------------------------------------------------------------------------
# The key itself
# ---------------------------------------------------------------------------


class TestTranscriptEntryKey:

    def test_uses_the_entry_uuid_when_present(self):
        key = _transcript_entry_key(
            {"uuid": "abc-123"}, "/tmp/some/transcript.jsonl", 7
        )
        assert key == "abc-123"

    def test_falls_back_to_a_PATH_QUALIFIED_index_without_a_uuid(self):
        """A bare line index is not unique across transcripts, and two
        projects can resolve from one cwd prefix. The fallback carries the
        path for that reason; a test asserting only ``"idx:7" in key`` would
        pass on an unqualified index too."""
        a = _transcript_entry_key({}, "/tmp/one.jsonl", 7)
        b = _transcript_entry_key({}, "/tmp/two.jsonl", 7)
        assert a == "/tmp/one.jsonl#idx:7"
        assert a != b, "the fallback key collides across transcripts"

    def test_an_empty_uuid_is_not_treated_as_a_key(self):
        """An empty string is falsy in the right direction here: every entry
        lacking a real uuid would otherwise share the key "", and the FIRST
        such entry to open a session would spend the key for all of them."""
        assert _transcript_entry_key({"uuid": ""}, "/tmp/t.jsonl", 3) == (
            "/tmp/t.jsonl#idx:3"
        )


# ---------------------------------------------------------------------------
# Both call sites
# ---------------------------------------------------------------------------


class TestBothCallSitesAreGuarded:

    def test_every_caller_of_the_open_scan_goes_through_the_guarded_function(
        self,
    ):
        """The reporter named ONE call site and there are two.

        A fix applied to the SessionEnd retry alone would have looked correct,
        passed a single-close test, and left the loop running through
        SessionStart. This pins that both entry points route through the one
        function that holds the guard, so a third caller added later inherits
        it instead of re-implementing the scan.

        PARSED, NOT GREPPED. A text match on the function name counts a
        docstring that merely mentions it; only a parser can tell a call from
        a mention.
        """
        source = Path(
            "app/services/hook_tracking.py"
        ).read_text()
        tree = ast.parse(source)

        callers: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "try_open_dwb_session_from_transcript"
                ):
                    callers.add(node.name)

        # Positive control: an AST pass that matches nothing satisfies any set
        # comparison against an empty expectation perfectly.
        assert callers, (
            "the scanner found no callers at all, which means it is not "
            "looking at what it thinks it is"
        )
        assert callers == {"handle_session_start", "handle_session_end"}, (
            f"the open scan has callers outside the two known hook entry "
            f"points: {sorted(callers)}. A new caller must inherit the "
            f"DWB-682 consumed-position guard, which lives inside "
            f"try_open_dwb_session_from_transcript."
        )
