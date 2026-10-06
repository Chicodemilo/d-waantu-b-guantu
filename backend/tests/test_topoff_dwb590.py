# Path: tests/test_topoff_dwb590.py
# File: test_topoff_dwb590.py
# Created: 2026-09-29 (DWB-590)
# Purpose: Guard top-off - that it is independent of memory_mode, honours its
#          own interval, counts relayed turns in BOTH shapes, and merges into
#          every return point instead of returning early.
# Caller: pytest
# Callees: app/services/hook_tracking, ast
# Data In: factory projects/agents, hook_sessions rows, UserPromptSubmit payloads
# Data Out: Assertions on the hook response and the persisted counter
# Last Modified: 2026-09-29 (DWB-590)

"""Tests for the top-off self-check.

The two that matter most are the ones guarding rulings rather than behaviour.

`TestIndependentOfMemoryMode` asserts top-off fires on a project in `stock`
mode AND that the top-off code path never reads `memory_mode` at the source
level. The columns share a table and a migration for delivery reasons only, and
the runtime test alone would keep passing if someone added a `memory_mode`
check that happened to be true in the fixture.

`TestMergesIntoEveryReturn` asserts a prompt that is BOTH the Nth AND a close
phrase still closes the session and still carries the check. Returning early on
the top-off branch would make a housekeeping feature silently eat a session
boundary, which is worse than the drift top-off exists to catch and would sit
undetected because the top-off output would look perfectly correct.
"""

import ast
import inspect
import textwrap

import pytest

from app.models.hook_session import HookSession
from app.models.project import MemoryMode, Project
from app.services import hook_tracking as svc

CWD = "/tmp/dwb590-repo"

# The two shapes the harness emits for a relayed teammate turn. The tag shape
# is the one _is_synthetic_user_text catches; the PROSE shape is the dominant
# one it misses by roughly ten to one, which is the DWB-592 bug. Top-off must
# count both, because it does not consult that filter at all.
RELAY_TAG = '<teammate-message teammate_id="tl">do the thing</teammate-message>'
RELAY_PROSE = "Another Claude session sent a message:\n\ndo the thing"


@pytest.fixture
def topoff_project(db_session, make_project, tmp_path):
    """A project with top-off ON and a short interval, in STOCK memory mode.

    Stock on purpose: it is the fixture that proves the independence ruling
    rather than assuming it.
    """
    project = make_project(repo_path=str(tmp_path))
    row = db_session.get(Project, project["id"])
    row.topoff_enabled = True
    row.topoff_interval = 3
    db_session.flush()
    return row


def _hook_session(db, *, project_id, session_id="dwb590-sess"):
    row = HookSession(
        session_id=session_id, project_id=project_id, total_tokens=0
    )
    db.add(row)
    db.flush()
    return row


def _prompt(db, project, *, text="just a normal prompt", session_id="dwb590-sess"):
    return svc.handle_user_prompt(
        db,
        {
            "prompt": text,
            "cwd": project.repo_path,
            "session_id": session_id,
            "hook_event_name": "UserPromptSubmit",
        },
    )


class TestIndependentOfMemoryMode:
    """ACCEPTANCE 1. The whole point of the ticket."""

    def test_fires_on_a_project_in_stock_mode(self, db_session, topoff_project):
        """Miles ruled top-off independent of memory mode and spec section 8
        agreed: it is about repetition and drift, not memory structure."""
        assert topoff_project.memory_mode == MemoryMode.stock
        _hook_session(db_session, project_id=topoff_project.id)

        for _ in range(2):
            interim = _prompt(db_session, topoff_project)
            assert interim["topoff"]["fired"] is False

        third = _prompt(db_session, topoff_project)

        assert third["topoff"]["fired"] is True
        assert third["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert third["hookSpecificOutput"]["additionalContext"].startswith(
            "\u2022\u2022TopOff Complete "
        )

    def test_fires_identically_in_human_memory_mode(self, db_session, topoff_project):
        """The other half of independence: turning the memory mode ON must not
        change top-off either. A feature 'independent' of a flag has to be
        unchanged in both of its positions, not just the default one."""
        topoff_project.memory_mode = MemoryMode.human_memory
        db_session.flush()
        _hook_session(db_session, project_id=topoff_project.id)

        results = [_prompt(db_session, topoff_project) for _ in range(3)]

        assert [r["topoff"]["fired"] for r in results] == [False, False, True]

    def test_topoff_source_reads_memory_mode_only_to_exclude_transitions(self):
        """The code-level half of acceptance 1, NARROWED by a later ruling.

        THIS ASSERTION USED TO BE "the name `memory_mode` never appears at
        all". That was the right shape for the ruling it encoded and it is now
        too wide, so it is narrowed here deliberately rather than deleted.

        The original ruling survives untouched: top-off is about repetition and
        drift, not memory structure, so it must behave IDENTICALLY in `stock`
        and in `human_memory`. The two runtime tests above are what hold that
        line, and they still pass unchanged.

        The later ruling (Miles, 2026-10-06): "top off shouldn't run while
        transition is in". That is not a statement about memory structure. It
        is a statement about the store being INCOMPLETE mid-flight, and the
        firing pass promotes a scar to CORE at a threshold, so running it
        against a half-migrated catalogue reaches the one tier `decide` refuses
        to let an agent choose.

        So the invariant is no longer "never reads the column" but "reads it
        for one reason only". A check against anything in TRANSITION_MODES is
        permitted; a check that could branch on stock vs human_memory is not,
        because that is the ruling the original assertion existed to protect
        and it is the one still worth protecting mechanically.
        """
        source = inspect.getsource(svc._topoff_for_prompt)
        tree = ast.parse(textwrap.dedent(source))

        comparisons = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and "memory_mode" in ast.dump(node)
        ]
        assert comparisons, (
            "expected the transition guard to compare memory_mode; if the guard "
            "moved, move this assertion with it rather than dropping it"
        )

        # Every memory_mode comparison must test membership of TRANSITION_MODES.
        # A direct `== MemoryMode.stock` or `== MemoryMode.human_memory` is the
        # thing this test exists to forbid, and it would read as reasonable in
        # a diff, which is exactly why it is asserted rather than trusted.
        for node in comparisons:
            dumped = ast.dump(node)
            assert "TRANSITION_MODES" in dumped, (
                "top-off may consult memory_mode ONLY to exclude an in-flight "
                "transition. Branching on stock vs human_memory is the "
                "dependence DWB-590 ruled out."
            )
            assert "stock" not in dumped and "human_memory" not in dumped

    def test_transition_modes_covers_every_in_flight_mode(self):
        """TRANSITION_MODES must name every mode in which the store is partial.

        A mode added to the enum later and forgotten here is the dangerous
        direction: the firing pass would run against a half-migrated catalogue
        and nothing would say so. Asserted against the enum rather than against
        a second hand-written list, so adding a mode fails this test instead of
        passing both copies.
        """
        settled = {MemoryMode.stock, MemoryMode.human_memory}
        in_flight = set(MemoryMode) - settled
        assert set(svc.TRANSITION_MODES) == in_flight

    @pytest.mark.parametrize("mode", [MemoryMode.adopting, MemoryMode.reverting])
    def test_does_not_fire_while_a_transition_is_in_flight(
        self, db_session, topoff_project, mode
    ):
        """Miles, 2026-10-06: "top off shouldn't run while transition is in".

        Parametrised over BOTH in-flight modes because `reverting` is the one
        that would be forgotten: adoption is the direction everyone pictures,
        and the store is just as partial on the way back out.
        """
        topoff_project.memory_mode = mode
        db_session.flush()
        _hook_session(db_session, project_id=topoff_project.id)

        results = [_prompt(db_session, topoff_project) for _ in range(4)]

        assert all(r["topoff"]["fired"] is False for r in results)
        assert all(
            r["topoff"]["reason"] == "transition_in_progress" for r in results
        )
        assert all(r["topoff"]["memory_mode"] == mode.value for r in results)

    def test_the_transition_block_does_not_consume_the_interval(
        self, db_session, topoff_project
    ):
        """The counter must not advance while the guard is holding.

        Otherwise a long adoption silently burns the interval, and the first
        prompt after cutover fires against a counter that has been ticking the
        whole time - top-off would come back mid-cycle instead of on a clean
        one, and nothing in the output would explain why.
        """
        topoff_project.memory_mode = MemoryMode.adopting
        db_session.flush()
        hook_session = _hook_session(db_session, project_id=topoff_project.id)

        for _ in range(5):
            _prompt(db_session, topoff_project)

        db_session.refresh(hook_session)
        assert not hook_session.prompt_count

    def test_resumes_on_its_own_after_cutover(self, db_session, topoff_project):
        """The guard is a pause, not an off switch.

        A transition that blocked top-off forever would be a far worse bug than
        the one it fixes, and it would present as "top-off stopped working"
        long after anyone connected it to a migration.
        """
        topoff_project.memory_mode = MemoryMode.adopting
        db_session.flush()
        _hook_session(db_session, project_id=topoff_project.id)

        for _ in range(3):
            assert _prompt(db_session, topoff_project)["topoff"]["fired"] is False

        topoff_project.memory_mode = MemoryMode.human_memory
        db_session.flush()

        results = [_prompt(db_session, topoff_project) for _ in range(3)]
        assert [r["topoff"]["fired"] for r in results] == [False, False, True]

    def test_disabled_project_response_is_unchanged(self, db_session, make_project, tmp_path):
        """Top-off off means the response is byte-identical to before this
        feature existed: no `topoff` key, no `hookSpecificOutput`. Every
        project is in this state today, so this is the shape almost every call
        actually returns."""
        project = make_project(repo_path=str(tmp_path))
        row = db_session.get(Project, project["id"])
        _hook_session(db_session, project_id=row.id)

        result = _prompt(db_session, row)

        assert result == {"status": "noop", "reason": "no_phrase_match"}


class TestInterval:
    """ACCEPTANCE 2. Configurable BECAUSE the number is a guess."""

    def test_default_interval_is_ten(self, db_session, make_project, tmp_path):
        """Spec section 8: 'let's start at an even 10 if we're guessing.'"""
        project = make_project(repo_path=str(tmp_path))
        assert db_session.get(Project, project["id"]).topoff_interval == 10

    def test_fires_only_on_multiples_of_a_non_default_interval(
        self, db_session, topoff_project
    ):
        topoff_project.topoff_interval = 4
        db_session.flush()
        _hook_session(db_session, project_id=topoff_project.id)

        fired = [_prompt(db_session, topoff_project)["topoff"]["fired"] for _ in range(9)]

        assert fired == [False, False, False, True, False, False, False, True, False]

    def test_the_injected_line_is_short_and_constant(self, db_session, topoff_project):
        """MILES'S RULING: "its short and the same every time... not a flood of
        bs", with the form `\u2022\u2022TopOff Complete <link>`.

        Asserts BOTH halves of that, because either one alone is satisfiable
        while violating him: a short line that varies is still noise to
        pattern-match against, and a constant block of four questions is still
        a flood. So this checks a length ceiling AND that two separate fires
        produce identical text.
        """
        _hook_session(db_session, project_id=topoff_project.id)
        seen = []
        for _ in range(6):
            r = _prompt(db_session, topoff_project)
            if r["topoff"]["fired"]:
                seen.append(r["hookSpecificOutput"]["additionalContext"])

        assert len(seen) == 2, "expected two fires at interval 3 over six prompts"
        assert seen[0] == seen[1], "the injected text must be the SAME every time"
        assert "\n" not in seen[0], f"must be one line, got: {seen[0]!r}"
        assert len(seen[0]) < 120, f"must be short, got {len(seen[0])} chars"

    def test_the_injected_line_carries_a_dashboard_link(
        self, db_session, topoff_project
    ):
        """Miles asked for a link to its page in DWB. The PAGE does not exist
        yet and building it is a follow-up ticket; the link shape is what
        ships, pointing where the view will live."""
        from app.config import settings

        _hook_session(db_session, project_id=topoff_project.id)
        for _ in range(2):
            _prompt(db_session, topoff_project)
        third = _prompt(db_session, topoff_project)

        line = third["hookSpecificOutput"]["additionalContext"]
        assert settings.DASHBOARD_BASE_URL in line
        assert f"/projects/{topoff_project.id}/topoff" in line

    def test_the_link_base_is_configurable_not_hardcoded(self):
        """DWB-574 shipped a hardcoded home directory that leaked a username
        into this repo. The dashboard host is a SETTING for the same reason:
        other people clone this on other machines and other ports."""
        from app.services import hook_tracking

        source = inspect.getsource(hook_tracking._topoff_for_prompt)
        assert "localhost" not in source, source
        assert "DASHBOARD_BASE_URL" in source

    def test_the_four_questions_are_not_injected(self, db_session, topoff_project):
        """The cost of Miles's ruling, asserted so it cannot drift back.

        An earlier build put the four questions in the payload verbatim. That
        is the flood he rejected. The marker is now the TRIGGER and the
        questions live in the playbook, which makes the check a rule behind a
        reference - weaker, and deliberately so. If someone re-adds them here,
        this fails and they have to argue with the ruling rather than quietly
        reverse it.
        """
        _hook_session(db_session, project_id=topoff_project.id)
        for _ in range(2):
            _prompt(db_session, topoff_project)
        line = _prompt(db_session, topoff_project)["hookSpecificOutput"][
            "additionalContext"
        ]
        for fragment in (
            "already answered",
            "what they asked for",
            "from a summary",
            "drifted from",
        ):
            assert fragment not in line, f"the four questions are back: {fragment!r}"

    def test_the_interval_is_still_reported_in_the_RESPONSE(
        self, db_session, topoff_project
    ):
        """The interval used to be printed in the injected text. Under Miles's
        ruling the text is constant, so it is not there any more.

        THIS IS NOT A DROPPED GUARD, IT IS A RELOCATED ONE. The old test
        existed to prove the interval is observable rather than buried in a
        constant. It still is - it moved from the human-facing line to the
        machine-readable response, which is the honest place for it now that
        the line is deliberately the same every time. Loosening the old
        assertion to make it pass would have turned a guard into decoration;
        asserting where the value actually went keeps it a guard.
        """
        _hook_session(db_session, project_id=topoff_project.id)
        for _ in range(2):
            interim = _prompt(db_session, topoff_project)
            assert interim["topoff"]["interval"] == 3
        third = _prompt(db_session, topoff_project)
        assert third["topoff"]["interval"] == 3
        assert third["topoff"]["prompt_count"] == 3
        # And deliberately NOT in the human-visible line. Asserted as EXACT
        # EQUALITY against the whole expected string rather than "3 is not in
        # it": my first version of this checked for the digit and failed,
        # because the dashboard port 5173 contains a 3. Substring checks on
        # short constants are a trap, and equality proves nothing leaked in at
        # all rather than proving one thing did not.
        from app.config import settings

        expected = (
            f"\u2022\u2022TopOff Complete {settings.DASHBOARD_BASE_URL}"
            f"/projects/{topoff_project.id}/topoff"
        )
        assert third["hookSpecificOutput"]["additionalContext"] == expected

    def test_zero_interval_is_guarded_not_a_crash(self, db_session, topoff_project):
        """The column is a plain int and an operator can set it to 0. Modulo by
        zero inside a fire-and-forget hook would be an exception on every
        prompt, so it is guarded and reported rather than trusted."""
        topoff_project.topoff_interval = 0
        db_session.flush()
        _hook_session(db_session, project_id=topoff_project.id)

        result = _prompt(db_session, topoff_project)

        assert result["topoff"]["fired"] is False
        assert result["topoff"]["reason"] == "invalid_interval"
        assert "hookSpecificOutput" not in result


class TestCountsRelayedTurns:
    """ACCEPTANCE 3, and the criterion that proves top-off is genuinely
    decoupled from the synthetic filter rather than incidentally passing."""

    @pytest.mark.parametrize(
        "relay,shape",
        [(RELAY_TAG, "tag-prefixed"), (RELAY_PROSE, "prose-prefixed")],
    )
    def test_relayed_turn_increments_the_counter(
        self, db_session, topoff_project, relay, shape
    ):
        """BOTH relay shapes count.

        The tag shape is caught by _is_synthetic_user_text and the prose shape
        is not, so if top-off consulted that filter these two would disagree.
        They must not: the counter is about how much has happened in the
        session, and a relayed teammate turn is something that happened.
        """
        session = _hook_session(db_session, project_id=topoff_project.id)

        result = _prompt(db_session, topoff_project, text=relay)

        assert result["topoff"]["counted"] is True, shape
        assert result["topoff"]["prompt_count"] == 1, shape
        db_session.refresh(session)
        assert session.prompt_count == 1, shape

    def test_both_shapes_count_the_same(self, db_session, topoff_project):
        """Asserted as a pair rather than only in parametrize, because the
        failure that matters is the two DIVERGING the day the harness changes
        its wording."""
        _hook_session(db_session, project_id=topoff_project.id)
        a = _prompt(db_session, topoff_project, text=RELAY_TAG)["topoff"]["prompt_count"]
        b = _prompt(db_session, topoff_project, text=RELAY_PROSE)["topoff"]["prompt_count"]
        assert (a, b) == (1, 2)

    def test_a_relayed_turn_still_does_not_drive_the_phrase_ladders(
        self, db_session, topoff_project
    ):
        """The uncoupling runs one way only. Top-off ignores the filter; the
        phrase ladders still obey it, because a false positive THERE destroys
        tracking data. A relayed close phrase must not close the session."""
        _hook_session(db_session, project_id=topoff_project.id)

        result = _prompt(
            db_session,
            topoff_project,
            text='<teammate-message id="x">shut down for the night</teammate-message>',
        )

        assert result["status"] == "noop"
        assert result["reason"] == "synthetic_prompt"
        assert result["topoff"]["counted"] is True


class TestPromptBeforeSessionStart:
    """The edge DWB-584 flagged and left here: a prompt with no hook_sessions
    row to count against."""

    def test_no_hook_session_is_a_named_noop_not_an_exception(
        self, db_session, topoff_project
    ):
        result = _prompt(db_session, topoff_project)

        assert result["topoff"]["counted"] is False
        assert result["topoff"]["reason"] == "no_hook_session"
        assert result["status"] == "noop"

    def test_no_session_id_is_a_different_named_reason(self, db_session, topoff_project):
        """Two distinct causes, two distinct reasons. Collapsing them would
        make 'the hook sent no session_id' indistinguishable from 'SessionStart
        has not landed yet', which are different problems."""
        result = svc.handle_user_prompt(
            db_session,
            {"prompt": "hello", "cwd": topoff_project.repo_path, "session_id": None},
        )
        assert result["topoff"]["reason"] == "no_session_id"

    def test_no_row_is_created_for_an_uncounted_prompt(self, db_session, topoff_project):
        """Creating one would invent a hook_sessions row with no transcript, no
        agent and no attribution, which token accounting keys on. Missing one
        prompt is cheaper than corrupting the cost record."""
        before = db_session.query(HookSession).count()
        _prompt(db_session, topoff_project)
        assert db_session.query(HookSession).count() == before


class TestMergesIntoEveryReturn:
    """ACCEPTANCE 4. The hard one."""

    def test_nth_prompt_that_is_also_a_close_phrase_still_closes(
        self, client, db_session, topoff_project
    ):
        """THE TEST THIS CRITERION EXISTS FOR.

        If the top-off branch returned early, this prompt would be counted,
        would emit a perfectly correct-looking check, and would SILENTLY fail
        to close the session. The top-off output would look right while the
        session record lost its end, which is why it could sit undetected for
        weeks.
        """
        from app.services import dwb_session as dwb_svc

        _hook_session(db_session, project_id=topoff_project.id)
        opened = client.post(
            "/api/sessions/open",
            json={"project_id": topoff_project.id, "open_method": "slash"},
        )
        assert opened.status_code in (200, 201)

        # Two prompts to sit just under the interval.
        for _ in range(2):
            _prompt(db_session, topoff_project)

        result = _prompt(
            db_session, topoff_project, text="ok, shut down for the night"
        )

        # BOTH things happened.
        assert result["status"] == "closed"
        assert result["close_phrase"] == "shut down for the night"
        assert result["topoff"]["fired"] is True
        assert "hookSpecificOutput" in result
        assert dwb_svc.get_active_session(db_session, topoff_project.id) is None

    def test_nth_prompt_that_is_also_an_open_phrase_still_opens(
        self, db_session, topoff_project
    ):
        from app.config.session_phrases import match_open
        from app.services import dwb_session as dwb_svc

        _hook_session(db_session, project_id=topoff_project.id)
        phrase = "you are archie, read the playbook"
        assert match_open(phrase), "fixture phrase must be in the open catalogue"

        for _ in range(2):
            _prompt(db_session, topoff_project)
        result = _prompt(db_session, topoff_project, text=phrase)

        assert result["status"] == "opened"
        assert result["topoff"]["fired"] is True
        assert dwb_svc.get_active_session(db_session, topoff_project.id) is not None

    def test_every_post_topoff_return_point_merges_it(self):
        """Structural guard over the source rather than one runtime case each.

        Every `return` statement in handle_user_prompt that is reachable AFTER
        the top-off block must spread `extra`. A runtime test per path would
        miss a seventh path added later; this fails the moment one is added
        without the merge.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(svc.handle_user_prompt)))

        # Returns before top-off runs legitimately carry nothing.
        allowed_bare = {"no_prompt", "no_project_for_cwd"}

        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                continue
            reason = None
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == "reason":
                    if isinstance(value, ast.Constant):
                        reason = value.value
            spreads = any(k is None for k in node.value.keys)
            if not spreads and reason not in allowed_bare:
                missing.append(reason or f"line {node.lineno}")

        assert missing == [], f"return points not merging top-off: {missing}"
