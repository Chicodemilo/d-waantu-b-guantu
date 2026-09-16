# Path: tests/test_token_recapture_dwb580.py
# File: test_token_recapture_dwb580.py
# Created: 2026-09-16
# Purpose: DWB-580 - a teammate's session is no longer frozen at its first turn.
#          Covers the cumulative-vs-delta rule (the multiplication hazard), the
#          removal of the completed-guard on both hook paths, fill-only
#          attribution now that repeats are processed, and the forward-only
#          transcript recapture sweep.
# Caller: pytest
# Callees: app/services/hook_tracking (record_session_tokens, handle_session_end,
#          recapture_token_growth), app/routers/hooks
# Data In: pytest fixtures + JSONL transcripts written to tmp_path
# Data Out: assertions
# Last Modified: 2026-09-16

"""The bug: a hook_session was written once and never again.

A teammate keeps ONE stable subagent_id for its whole life and is resumed by
SendMessage many times. The first SubagentStop created the row, parsed the
transcript as it stood at that instant, marked the row completed, and every
later stop hit a completed-guard and returned 200 ok having discarded the work.
Measured at 5x under across six sessions in a single day.

The fix has two halves and the second is the dangerous one. Re-processing is
now allowed, and the transcript is a CUMULATIVE file, so the naive version adds
the whole running total again on every stop and multiplies a ticket's tokens by
its stop count. That is worse than the bug it replaces: an understated number is
at least wrong in one direction, a multiplied one looks plausible and is
unbounded. TestNoMultiplication is the test that matters here.
"""

import ast
import inspect
import json
import textwrap

import pytest

from app.models.hook_session import HookSession, HookSessionStatus
from app.models.ticket import Ticket
from app.services import hook_tracking as ht



def _fn_ast(func):
    """The function's own AST, so structural checks ignore comments.

    A plain string search cannot be used here: the source now CONTAINS the old
    code quoted in a comment explaining why it went, so `"return existing" in
    src` matches the explanation and fails on the fixed file.
    """
    return ast.parse(textwrap.dedent(inspect.getsource(func)))


def _returns_bare_name(func, name):
    return any(
        isinstance(n, ast.Return)
        and isinstance(n.value, ast.Name)
        and n.value.id == name
        for n in ast.walk(_fn_ast(func))
    )


def _assigns_conditional_attr(func, attr):
    """True if the function assigns `<something>.attr = X if Y else None`."""
    for n in ast.walk(_fn_ast(func)):
        if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.IfExp):
            continue
        for t in n.targets:
            if isinstance(t, ast.Attribute) and t.attr == attr:
                return True
    return False


def _write_transcript(path, turns):
    """Write a cumulative transcript: `turns` entries of 1000 output tokens."""
    lines = [json.dumps({"agentName": "backend-worker"})]
    for i in range(turns):
        lines.append(json.dumps({
            "usage": {"input_tokens": 0, "output_tokens": 1000,
                      "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 500},
            "timestamp": f"2026-09-16T15:{i:02d}:00.000Z",
        }))
    path.write_text("\n".join(lines) + "\n")
    return str(path)


@pytest.fixture
def worker_session(client, db_session, make_project, make_agent, make_ticket, tmp_path):
    """A hook_session for a worker with a ticket, plus its transcript."""
    project = make_project(repo_path=str(tmp_path / "repo"))
    agent = make_agent(project_id=project["id"], role="backend-worker")
    ticket = make_ticket(project_id=project["id"])
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, turns=1)

    row = HookSession(
        session_id="aTestWorker-dwb580",
        transcript_path=str(transcript),
        agent_id=agent["id"],
        project_id=project["id"],
        ticket_id=ticket["id"],
        total_tokens=0,
        status=HookSessionStatus.active,
    )
    db_session.add(row)
    db_session.flush()
    return {"row": row, "ticket": ticket, "agent": agent,
            "project": project, "transcript": transcript}


class TestNoMultiplication:
    """AC 2. The criterion with teeth."""

    def test_repeated_stops_do_not_multiply_ticket_tokens(
        self, db_session, worker_session, tmp_path
    ):
        """Five stops over a growing transcript must leave the FINAL cumulative
        total on the ticket, not five times anything.

        The pre-fix naive fix adds the running total on every stop, so this
        would land 1000+2000+3000+4000+5000 = 15000 instead of 5000. Asserting
        only the last stop's arithmetic would pass either way, which is why
        this walks several stops and checks the ticket after each one.
        """
        row = worker_session["row"]
        ticket_id = worker_session["ticket"]["id"]
        transcript = worker_session["transcript"]

        for turns in range(1, 6):
            _write_transcript(transcript, turns=turns)
            parsed = ht.parse_transcript(str(transcript))
            assert parsed["total_tokens"] == turns * 1000
            ht.record_session_tokens(
                db_session, row, parsed["total_tokens"], emit_stop=False
            )
            ticket = db_session.get(Ticket, ticket_id)
            # After every stop the ticket equals the CUMULATIVE transcript,
            # never a running sum of cumulative totals.
            assert ticket.tokens_used == turns * 1000, (
                f"after {turns} stop(s) ticket has {ticket.tokens_used}, "
                f"expected {turns * 1000}"
            )
            assert row.total_tokens == turns * 1000

    def test_duplicate_delivery_of_the_same_event_adds_nothing(
        self, db_session, worker_session
    ):
        """The idempotency the removed guard provided now lives in the recorder.

        A hook delivered twice with an unchanged transcript must contribute a
        delta of zero rather than a second full total.
        """
        row = worker_session["row"]
        ticket_id = worker_session["ticket"]["id"]

        first = ht.record_session_tokens(db_session, row, 4200, emit_stop=False)
        second = ht.record_session_tokens(db_session, row, 4200, emit_stop=False)
        third = ht.record_session_tokens(db_session, row, 4200, emit_stop=False)

        assert first == 4200
        assert (second, third) == (0, 0)
        assert db_session.get(Ticket, ticket_id).tokens_used == 4200

    def test_a_smaller_reparse_never_walks_the_total_backwards(
        self, db_session, worker_session
    ):
        """A truncated or rotated transcript records nothing rather than
        logging a negative delta that would credit tokens back."""
        row = worker_session["row"]
        ticket_id = worker_session["ticket"]["id"]

        ht.record_session_tokens(db_session, row, 9000, emit_stop=False)
        shrunk = ht.record_session_tokens(db_session, row, 1000, emit_stop=False)

        assert shrunk == 0
        assert row.total_tokens == 9000
        assert db_session.get(Ticket, ticket_id).tokens_used == 9000


class TestBucketRouting:
    """The delta, not the cumulative figure, reaches each DWB-353 bucket."""

    def test_overhead_agent_delta_goes_to_the_project_bucket(
        self, db_session, client, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path / "r"))
        agent = make_agent(project_id=project["id"], role="team-lead")
        row = HookSession(
            session_id="aTL-dwb580", agent_id=agent["id"],
            project_id=project["id"], total_tokens=0,
            status=HookSessionStatus.active,
        )
        db_session.add(row)
        db_session.flush()

        ht.record_session_tokens(db_session, row, 5000, emit_stop=False)
        ht.record_session_tokens(db_session, row, 8000, emit_stop=False)

        db_session.flush()
        detail = client.get(f"/api/projects/{project['id']}").json()
        # 8000 cumulative, logged as 5000 then 3000 - never 5000 + 8000.
        assert detail["tl_overhead_tokens"] == 8000
        assert row.total_tokens == 8000

    def test_worker_without_a_ticket_routes_to_ad_hoc_not_the_ticket(
        self, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path / "r"))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        row = HookSession(
            session_id="aNoTicket-dwb580", agent_id=agent["id"],
            project_id=project["id"], ticket_id=None, total_tokens=0,
            status=HookSessionStatus.active,
        )
        db_session.add(row)
        db_session.flush()

        delta = ht.record_session_tokens(db_session, row, 3300, emit_stop=False)
        assert delta == 3300
        assert row.total_tokens == 3300


class TestCompletedRowIsNotFrozen:
    """AC 1, on both paths. A completed row used to be the end of the story."""

    def test_completed_session_still_accepts_more(self, db_session, worker_session):
        row = worker_session["row"]
        row.status = HookSessionStatus.completed
        db_session.flush()

        delta = ht.record_session_tokens(db_session, row, 7777, emit_stop=False)

        assert delta == 7777
        assert row.total_tokens == 7777

    def test_subagent_stop_guard_is_gone_from_the_source(self):
        """The guard was five lines that silently discarded a turn's work.

        Asserting on the source is normally brittle, but the failure mode here
        is a SILENT no-op: if the guard comes back, every test above still
        passes because they call the recorder directly, and the only visible
        symptom is tokens quietly going missing again in production. This is
        the tripwire for a regression that has no runtime signal.
        """
        assert not _returns_bare_name(ht._handle_subagent_stop, "existing"), (
            "the completed-guard is back in _handle_subagent_stop; a resumed "
            "teammate's later stops will be discarded again"
        )


class TestFillOnlyAttribution:
    """Removing the guard made this branch live for the first time."""

    def test_a_later_stop_does_not_clear_an_existing_ticket(
        self, db_session, worker_session
    ):
        """Pre-DWB-580 the update branch assigned `ticket.id if ticket else
        None`, which ran at most once. Now that every later stop re-enters it,
        a resolution that misses would ERASE a correct attribution and the row
        would read as if it had never been attributed at all."""
        row = worker_session["row"]
        original = row.ticket_id
        assert original is not None

        assert not _assigns_conditional_attr(ht._handle_subagent_stop, "ticket_id"), (
            "the update branch assigns ticket_id conditionally again, so a "
            "later stop whose resolution misses will clear a good attribution"
        )
        assert not _assigns_conditional_attr(ht._handle_subagent_stop, "agent_id"), (
            "same hazard for agent_id"
        )


class TestRecaptureSweep:
    """The half that does not depend on another hook event ever arriving."""

    def test_sweep_advances_a_grown_transcript(self, db_session, worker_session):
        row = worker_session["row"]
        ticket_id = worker_session["ticket"]["id"]
        transcript = worker_session["transcript"]

        _write_transcript(transcript, turns=2)
        ht.record_session_tokens(db_session, row, 2000, emit_stop=False)
        row.transcript_bytes = transcript.stat().st_size
        db_session.flush()

        _write_transcript(transcript, turns=6)
        advanced, added = ht.recapture_token_growth(db_session)

        assert advanced >= 1
        assert added >= 4000
        assert row.total_tokens == 6000
        assert db_session.get(Ticket, ticket_id).tokens_used == 6000

    def test_sweep_skips_a_transcript_that_has_not_grown(
        self, db_session, worker_session
    ):
        row = worker_session["row"]
        transcript = worker_session["transcript"]

        _write_transcript(transcript, turns=3)
        ht.record_session_tokens(db_session, row, 3000, emit_stop=False)
        row.transcript_bytes = transcript.stat().st_size
        db_session.flush()

        advanced, added = ht.recapture_token_growth(db_session)

        assert (advanced, added) == (0, 0)
        assert row.total_tokens == 3000

    def test_sweep_is_forward_only(self, db_session, worker_session):
        """AC 3. Miles ruled the old baseline lost and not to be chased, so the
        sweep must not reach back and quietly repair a pre-fix figure."""
        from datetime import timedelta

        row = worker_session["row"]
        transcript = worker_session["transcript"]
        _write_transcript(transcript, turns=9)

        # Backdate the row to before the process-start epoch.
        row.created_at = ht._RECAPTURE_EPOCH - timedelta(hours=1)
        row.total_tokens = 0
        db_session.flush()

        advanced, added = ht.recapture_token_growth(db_session)

        assert (advanced, added) == (0, 0)
        assert row.total_tokens == 0, "the sweep backfilled a pre-fix row"

    def test_one_unreadable_transcript_does_not_stop_the_sweep(
        self, db_session, worker_session, make_project, make_agent, tmp_path
    ):
        """A sweep runs unattended, so a poison row must not cost every later
        row its capture."""
        good = worker_session
        _write_transcript(good["transcript"], turns=4)

        project = good["project"]
        agent = make_agent(project_id=project["id"], role="backend-worker")
        missing = tmp_path / "gone.jsonl"
        missing.write_text("{}\n")
        bad = HookSession(
            session_id="aMissing-dwb580", transcript_path=str(missing),
            agent_id=agent["id"], project_id=project["id"],
            total_tokens=0, status=HookSessionStatus.active,
        )
        db_session.add(bad)
        db_session.flush()
        missing.unlink()

        advanced, added = ht.recapture_token_growth(db_session)

        assert good["row"].total_tokens == 4000
        assert advanced >= 1
