# Path: tests/test_gate_status_coverage_dwb678.py
# File: test_gate_status_coverage_dwb678.py
# Created: 2026-10-12 (DWB-678)
# Purpose: Behavioural half of DWB-678 - gate-status returns every gate sprint
#          close enforces, and never reports a verdict over a set it did not
#          evaluate.
# Caller: pytest
# Callees: GET /api/projects/{id}/gate-status, PATCH /api/sprints/{id} (over HTTP)
# Data In: factory-created projects + sprints via conftest
# Data Out: assertions on the gate list, all_passing, covered_passing, unevaluated
# Last Modified: 2026-10-12 (DWB-678)

"""DWB-678: the endpoint returned six of the nine gates that close enforces,
and summarised those six under a field named `all_passing`.

THE TRAP, AND IT IS WHY THE CENTRAL TEST WALKS A SEQUENCE RATHER THAN CHECKING
A FIELD. A TL reads gate-status, sees every gate passing, closes the sprint,
and the close is refused by a gate that was never in the answer. Asserting that
a field changed shape would not show that; attempting the close does.

THE CENTRAL TEST IS WRITTEN AS AN OUTCOME, NOT AS EITHER FIX. "A gate that
blocks the close is visible, and nothing in the response says the close will
succeed" holds whether the endpoint returns the gate (what shipped) or merely
declares it unevaluated (the interim design). A test phrased against one
mechanism would have had to be rewritten when the scope changed, and a test
rewritten alongside the code it guards has stopped being evidence.

THIS FILE IMPORTS NOTHING THE FIX INTRODUCED, AND THAT IS LOAD-BEARING. Its job
includes characterising the BEFORE state, so its import graph must be
satisfiable in that state: run against the pre-fix tree it must FAIL on an
assertion carrying its own message, not die at collection on a missing symbol.
An ImportError would degrade the proof from "the endpoint hides a blocking
gate" to "this file does not import". The unit tests that need the new helpers
live in tests/test_gate_status_internals_dwb678.py. Do not merge them.

Demonstrated 2026-10-12 against a detached worktree at the pre-fix commit: see
the class docstrings below for the exact assertion each one failed on.
"""


def _gate_status(client, project_id: int) -> dict:
    r = client.get(f"/api/projects/{project_id}/gate-status")
    assert r.status_code == 200, r.text
    return r.json()


def _gate(payload: dict, toggle: str) -> dict | None:
    return next((g for g in payload["gates"] if g.get("toggle") == toggle), None)


class TestTheTrap:
    """A gate that blocks the close must be visible before the close.

    Pre-fix failure: "force_test_run blocks the close and is absent from
    gate-status".
    """

    def test_a_close_blocking_gate_is_visible_and_the_close_is_refused(
        self, client, make_project, make_sprint, tmp_path
    ):
        project = make_project(
            repo_path=str(tmp_path),
            force_handoff_md=False,  # default True; would fail for the wrong reason
            force_test_run=True,     # enforced at close
        )
        sprint = make_sprint(project_id=project["id"], status="active")

        payload = _gate_status(client, project["id"])

        gate = _gate(payload, "force_test_run")
        assert gate is not None, (
            "force_test_run blocks the close and is absent from gate-status; "
            f"returned toggles: {[g.get('toggle') for g in payload['gates']]}"
        )
        assert gate["passing"] is False, gate

        # No reading of this response says the close will succeed.
        assert payload["all_passing"] is not True, payload["all_passing"]
        assert payload["covered_passing"] is False

        # THE SEQUENCE WALK. The close really is refused, and by the gate the
        # endpoint showed failing. Asserting the REASON, not merely the
        # rejection: a 400 for an unrelated gate reads identically.
        r = client.patch(
            f"/api/sprints/{sprint['id']}", json={"status": "completed"}
        )
        assert r.status_code == 400, r.text
        assert "force_test_run" in r.json()["detail"], r.json()

    def test_the_close_succeeds_once_the_gate_is_satisfied(
        self, client, make_project, make_sprint, make_test_result, tmp_path
    ):
        """The opposite-mode case, in the same file.

        Without it, the refusal above could be produced by a close that never
        succeeds for any reason, and every assertion would still pass.
        """
        project = make_project(
            repo_path=str(tmp_path),
            force_handoff_md=False,
            force_test_run=True,
        )
        sprint = make_sprint(project_id=project["id"], status="active")
        make_test_result(project_id=project["id"])

        payload = _gate_status(client, project["id"])
        assert _gate(payload, "force_test_run")["passing"] is True
        assert payload["all_passing"] is True, (
            "every gate is evaluated and passing, so the endpoint should now "
            f"be able to say so; got {payload['all_passing']!r}"
        )

        r = client.patch(
            f"/api/sprints/{sprint['id']}", json={"status": "completed"}
        )
        assert r.status_code == 200, r.text


class TestEveryEnforcedGateIsReturned:
    """The gate list and the enforcement must agree about which gates exist.

    Pre-fix failure: three toggles missing from the returned set.
    """

    def test_the_returned_gates_cover_every_model_toggle(
        self, client, make_project, make_sprint, tmp_path
    ):
        from app.models.project import Project

        project = make_project(repo_path=str(tmp_path))
        make_sprint(project_id=project["id"], status="active")
        payload = _gate_status(client, project["id"])

        model_toggles = {
            c.name for c in Project.__table__.columns
            if c.name.startswith("force_")
        }
        # Anti-vacuous: an empty model scan makes the comparison free.
        assert model_toggles, "no force_ columns found on Project"

        returned = {g["toggle"] for g in payload["gates"]}
        assert returned == model_toggles, (
            f"gate-status omits {sorted(model_toggles - returned)}; "
            f"returns unknown {sorted(returned - model_toggles)}"
        )
        assert payload["unevaluated_gates"] == []

    def test_every_gate_entry_carries_the_toggle_the_derivation_reads(
        self, client, make_project, tmp_path
    ):
        """The derivation keys on g["toggle"]; a gate without one is invisible.

        It would silently move from evaluated to unevaluated and the endpoint
        would report a gate as unchecked while checking it.
        """
        project = make_project(repo_path=str(tmp_path))
        payload = _gate_status(client, project["id"])

        assert payload["gates"], "no gates returned; nothing is being asserted"
        missing = [g for g in payload["gates"] if not g.get("toggle")]
        assert not missing, f"gate entries without a toggle key: {missing}"


class TestSprintScopedGatesWithoutASprint:
    """The one state that still produces an unevaluated set, and it is honest.

    force_test_run and force_consolidation are defined over a sprint window.
    With no active sprint there is no verdict to give, so they are omitted and
    reported as unevaluated rather than guessed at.
    """

    def test_they_are_unevaluated_and_all_passing_is_null(
        self, client, make_project, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), force_handoff_md=False)
        payload = _gate_status(client, project["id"])

        assert set(payload["unevaluated_gates"]) == {
            "force_test_run",
            "force_consolidation",
        }
        assert payload["covered_passing"] is True
        assert payload["all_passing"] is None, (
            "covered gates pass but two were not evaluated, so the endpoint "
            f"cannot answer; got {payload['all_passing']!r}"
        )

    def test_the_note_says_why_rather_than_where_to_look(
        self, client, make_project, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), force_handoff_md=False)
        note = _gate_status(client, project["id"])["coverage_note"]

        assert note, "gates are unevaluated but the note is empty"
        assert "no active sprint" in note
        assert "force_test_run" in note
        assert "force_consolidation" in note
        assert "_check_completion_gates" in note

    def test_a_failing_covered_gate_still_reports_false_not_none(
        self, client, make_project, tmp_path
    ):
        """False is truthful under partial coverage and must not be softened.

        A covered gate failing means the close is refused whatever the
        unevaluated gates would say, so None here would discard a real answer.
        """
        project = make_project(
            repo_path=str(tmp_path),
            force_handoff_md=True,  # HANDOFF.md deliberately absent from tmp_path
        )
        payload = _gate_status(client, project["id"])

        assert payload["unevaluated_gates"], "no unevaluated gates; wrong fixture"
        assert payload["covered_passing"] is False
        assert payload["all_passing"] is False


class TestTestCoverageGateDoesNotBreakTheRead:
    """force_test_coverage refuses a CLOSE with a 400 on an unreadable repo.

    A GET must not inherit that. Pre-fix this gate was simply absent, so the
    endpoint could not fail this way; adding it is what creates the risk.
    """

    def test_an_unreadable_repo_reports_rather_than_500s(
        self, client, make_project, make_sprint, tmp_path
    ):
        project = make_project(
            repo_path=str(tmp_path),  # not shaped like a FastAPI backend
            force_handoff_md=False,
            force_test_coverage=True,
        )
        make_sprint(project_id=project["id"], status="active")

        payload = _gate_status(client, project["id"])  # asserts 200 inside

        gate = _gate(payload, "force_test_coverage")
        assert gate is not None
        assert gate["evaluable"] is False
        assert gate["reason"], "unevaluable gate must say why"
        # The close WILL refuse for this reason, so the gate must not read as
        # passing - that would be this ticket's trap, one layer in.
        assert gate["passing"] is False
        assert payload["all_passing"] is False

    def test_a_disabled_coverage_gate_does_not_touch_the_filesystem(
        self, client, make_project, tmp_path
    ):
        """Disabled means no evaluation, matching the close's `if` exactly."""
        project = make_project(
            repo_path=str(tmp_path),
            force_handoff_md=False,
            force_test_coverage=False,
        )
        gate = _gate(_gate_status(client, project["id"]), "force_test_coverage")

        assert gate["enabled"] is False
        assert gate["passing"] is True
        assert gate["evaluable"] is True
