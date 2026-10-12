# Path: tests/test_gate_status_internals_dwb678.py
# File: test_gate_status_internals_dwb678.py
# Created: 2026-10-12 (DWB-678)
# Purpose: Unit half of DWB-678 - the pure three-valued summary, the derived
#          toggle enumeration, and the read-route table behind coverage_note.
# Caller: pytest
# Callees: app/routers/projects.py (_summarise_all_passing, _all_gate_toggles,
#          _coverage_note)
# Data In: plain values; no DB, no HTTP
# Data Out: assertions on the helpers' return values
# Last Modified: 2026-10-12 (DWB-678)

"""DWB-678, the half that NEEDS the new symbols.

SPLIT FROM tests/test_gate_status_coverage_dwb678.py ON PURPOSE, AND NOT FOR
TIDINESS. That file characterises the pre-fix behaviour, so its import graph
must be satisfiable against the pre-fix tree or it dies at collection and
proves nothing. This file imports three symbols the fix introduces and
therefore CANNOT load against that tree, which is exactly why it is separate.
Do not merge them back.

What lives here is the decision logic exercised directly, one branch at a time,
so each is pinned independently of whatever the live data happens to be able to
produce. The endpoint tests in the sibling file cover the states real projects
reach; these cover the function's contract whether or not a project currently
reaches them.
"""

from app.routers.projects import _all_gate_toggles, _summarise_all_passing


class TestAllPassingIsThreeValued:
    def test_false_when_a_covered_gate_fails(self):
        assert _summarise_all_passing(False, ["force_test_run"]) is False

    def test_false_survives_even_with_nothing_unevaluated(self):
        assert _summarise_all_passing(False, []) is False

    def test_none_when_covered_pass_but_something_is_unevaluated(self):
        assert _summarise_all_passing(True, ["force_test_run"]) is None

    def test_true_only_when_nothing_is_unevaluated(self):
        """The verdict a fully-evaluated project gets.

        Reachable through the endpoint - a project with an active sprint and
        every gate passing - and asserted here too, because the endpoint route
        depends on live gate state while this pins the contract directly.
        """
        assert _summarise_all_passing(True, []) is True

    def test_none_is_falsy_so_the_naive_caller_reads_it_safely(self):
        """The property the design rests on, asserted rather than assumed.

        A caller writing `if all_passing:` must NOT be told the close will
        succeed. None is falsy in Python and null is falsy in JS, so the naive
        read lands on the safe side. If this ever changed, the field would
        become dangerous in exactly the hands it was designed for.
        """
        assert not _summarise_all_passing(True, ["force_test_run"])
        assert not _summarise_all_passing(False, [])
        assert _summarise_all_passing(True, [])


class TestToggleEnumerationIsDerived:
    def test_every_toggle_comes_from_the_model_and_is_well_formed(self):
        toggles = _all_gate_toggles()

        assert toggles, "no force_ toggles found; the enumeration saw nothing"
        assert toggles == sorted(toggles), "callers rely on a stable order"
        assert all(t.startswith("force_") for t in toggles)
        assert len(toggles) == len(set(toggles))

    def test_the_enumeration_matches_the_model_exactly(self):
        """Second instrument on the same question, read the other way.

        _all_gate_toggles reads Project.__table__; this reads the mapped
        attributes. Two paths to the same set, so a change to either one that
        drops a column shows up as disagreement rather than as a quietly
        shorter list.
        """
        from app.models.project import Project

        from_attrs = sorted(
            name for name in vars(Project) if name.startswith("force_")
        )
        assert from_attrs, "no force_ attributes on Project"
        assert _all_gate_toggles() == from_attrs


class TestATenthGateStillReportsItself:
    """The property that survives the full-scope fix.

    All nine gates are returned now, so `unevaluated_gates` is empty on any
    project with an active sprint and the derivation LOOKS inert. It is not:
    it is the thing that makes a gate added later announce itself instead of
    going missing the way three of them did. With nothing currently
    unevaluated, nothing else in the suite would notice if someone replaced
    the derivation with a literal `[]`.
    """

    def test_a_model_toggle_the_handler_ignores_lands_in_unevaluated(
        self, client, make_project, make_sprint, tmp_path, monkeypatch
    ):
        """Simulate the tenth column at the seam that reads the model.

        _all_gate_toggles IS the model-reading step, so patching it is exactly
        equivalent to the model having grown a force_ column that no gate
        builder knows about - without migrating a throwaway column onto a
        shared test database.
        """
        from app.routers import projects as projects_router

        real = projects_router._all_gate_toggles()
        monkeypatch.setattr(
            projects_router,
            "_all_gate_toggles",
            lambda: sorted([*real, "force_a_gate_nobody_wired"]),
        )

        project = make_project(repo_path=str(tmp_path), force_handoff_md=False)
        make_sprint(project_id=project["id"], status="active")

        payload = client.get(
            f"/api/projects/{project['id']}/gate-status"
        ).json()

        assert payload["unevaluated_gates"] == ["force_a_gate_nobody_wired"], (
            "a model toggle with no gate builder must report itself as "
            f"unevaluated; got {payload['unevaluated_gates']}"
        )
        assert payload["all_passing"] is None, (
            "an unexamined gate must stop all_passing being True even when "
            f"every evaluated gate passes; got {payload['all_passing']!r}"
        )
        assert "force_a_gate_nobody_wired" in payload["coverage_note"]
        assert "no read route known" in payload["coverage_note"]

    def test_without_the_patch_the_same_project_is_fully_covered(
        self, client, make_project, make_sprint, tmp_path
    ):
        """The control. Without it the test above could pass against a handler
        that reports everything as unevaluated."""
        project = make_project(repo_path=str(tmp_path), force_handoff_md=False)
        make_sprint(project_id=project["id"], status="active")

        payload = client.get(
            f"/api/projects/{project['id']}/gate-status"
        ).json()

        assert payload["unevaluated_gates"] == []
        assert payload["coverage_note"] is None


class TestTheNoteFallback:
    """The OUTCOME at the fallback, not the contents of the table behind it.

    Two parametrised tests used to live here asserting that every entry in
    _GATE_READ_ROUTES named a real toggle and a real API path. They were
    deleted: nothing reads those entries today (the lookup at
    projects.py:951 is live but always misses, because every toggle that
    reaches `unevaluated` either carries a reason or is a column nobody has
    wired), so both passed forever regardless of whether the endpoint behaved.
    A green check cited as coverage of something it does not touch is the
    defect this sprint is named after, and it does not get an exemption for
    being mine.

    What matters if the fallback fires is that the caller gets a usable
    string. That is asserted below, and the miss arm is also covered end to
    end by test_a_model_toggle_the_handler_ignores_lands_in_unevaluated. The
    hit arm cannot be constructed without patching the handler itself, so per
    the ruling it does not want a test.
    """

    def test_a_toggle_with_no_route_is_reported_rather_than_omitted(self):
        """The fallback is the honest answer for a gate nobody has wired.

        Asserted on the note builder directly, with a toggle that does not
        exist, because the alternative - waiting for someone to add a tenth
        gate - means this path is first exercised in production.
        """
        from app.routers.projects import _coverage_note

        note = _coverage_note(["force_not_a_real_gate"])

        assert note is not None
        assert "force_not_a_real_gate" in note
        assert "no read route known" in note

    def test_the_note_is_none_when_nothing_is_unevaluated(self):
        """Absence of the field is itself the signal that coverage is whole."""
        from app.routers.projects import _coverage_note

        assert _coverage_note([]) is None
