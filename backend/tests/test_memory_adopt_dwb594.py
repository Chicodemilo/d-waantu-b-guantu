# Path: tests/test_memory_adopt_dwb594.py
# File: test_memory_adopt_dwb594.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Guard the snapshot phase - determinism across runs, the dry run
#          writing nothing, and the states that must stay distinguishable
#          (no memory vs unreadable vs no candidates).
# Caller: pytest
# Callees: app.services.memory_adopt
# Data In: lat_test rows plus memory.md files under tmp_path
# Data Out: assertions
# Last Modified: 2026-09-30 (DWB-594)

"""DWB-594 phase 1, the snapshot.

Acceptance 1 (deterministic) and acceptance 5 (a dry run writes nothing) both
live here. The rest of 594 - the one-at-a-time decide interface, the sweep and
the cutover freeze - is not built yet.

The tests that matter most are the ones separating states that all produce zero
candidates: an agent who never wrote, an agent whose file will not read, and an
agent whose file holds no lessons. Those are three different facts and adopting
past the middle one loses that agent's memory at cutover.
"""

import os
from pathlib import Path

import pytest

from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionState,
)
from app.models.project import Project
from app.services import memory_adopt

SAMPLE = """## 2026-09-29T12:00:00+00:00 - condensed
# Memory - Someone

Durable lessons only.

## Verification discipline

- A green test run and a RECORDED test run are different facts.
  Verify the post landed by querying the endpoint.
- Never live-test a write path against a shared database.

## Migrations

Autogenerate misses INT to BIGINT widenings; hand-write them.
"""


def _write_memory(tmp_path, prefix, name, text):
    d = Path(tmp_path) / ".dwb" / "memory" / prefix / name
    d.mkdir(parents=True, exist_ok=True)
    path = d / "memory.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def adopting_project(make_project, make_agent, make_project_agent, tmp_path):
    """A project with one agent who has written a real memory file."""
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"], name="Snapshotted")
    _write_memory(tmp_path, project["prefix"], "Snapshotted", SAMPLE)
    return project, agent


def _project(db_session, project_dict) -> Project:
    return db_session.get(Project, project_dict["id"])


def _run(db_session, project_dict) -> MemoryTransitionRun:
    """An open adopt run. DWB-593 moved `direction` onto the run, so an entry
    without one is the orphan that table exists to make impossible."""
    run = MemoryTransitionRun(
        project_id=project_dict["id"], direction=TransitionDirection.adopt
    )
    db_session.add(run)
    db_session.flush()
    return run


class TestDeterminism:
    """DWB-594 acceptance 1."""

    def test_two_runs_on_an_unchanged_file_produce_identical_candidates(
        self, db_session, adopting_project
    ):
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)

        # ONE run, reused. DWB-593 enforces at most one OPEN run per project
        # with a generated column and a composite UNIQUE, so a second open run
        # is not merely unnecessary here - it is illegal. Reusing it is also the
        # sharper assertion: what must be deterministic is the ENUMERATOR, not
        # the act of creating a run.
        run = _run(db_session, project_dict)
        first = memory_adopt.enumerate_candidates(
            db_session, project, run, persist=False
        )
        second = memory_adopt.enumerate_candidates(
            db_session, project, run, persist=False
        )

        assert first.candidate_count > 0, "fixture produced no candidates"
        assert [r.source_excerpt for r in first.rows] == [
            r.source_excerpt for r in second.rows
        ]
        assert [r.agent_id for r in first.rows] == [r.agent_id for r in second.rows]

    def test_candidates_are_the_lessons_not_the_headings(
        self, db_session, adopting_project
    ):
        """Three lessons in the fixture: two bullets and one prose paragraph.

        The ISO provenance line, the `# Memory` title and the two `##` section
        headings are NOT candidates - nobody is asked to tier a timestamp or a
        section title.
        """
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        assert result.candidate_count == 3, [r.source_excerpt for r in result.rows]

    def test_the_heading_chain_survives_into_the_excerpt(
        self, db_session, adopting_project
    ):
        """No heading_path column exists, so the chain rides in source_excerpt
        via the shared renderer and must come back out through the shared
        splitter. This is the property that made the column unnecessary."""
        from app.services import memory_format

        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        rows = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        ).rows

        recovered = [memory_format.split(r.source_excerpt).entries[0] for r in rows]
        assert all(e.heading_path for e in recovered), [
            (e.heading_path, e.body[:40]) for e in recovered
        ]
        assert recovered[0].heading_path == ("Verification discipline",)
        assert recovered[-1].heading_path == ("Migrations",)


class TestDryRun:
    """DWB-594 acceptance 5: the dry run writes nothing."""

    def test_a_dry_run_persists_no_rows(self, db_session, adopting_project):
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)

        before = db_session.query(MemoryTransition).count()
        result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        db_session.flush()
        after = db_session.query(MemoryTransition).count()

        assert result.candidate_count > 0, "dry run produced nothing to check"
        assert after == before

    def test_a_dry_run_leaves_the_file_byte_identical(
        self, db_session, adopting_project, tmp_path
    ):
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        path = (
            tmp_path
            / ".dwb"
            / "memory"
            / project_dict["prefix"]
            / "Snapshotted"
            / "memory.md"
        )
        before_bytes = path.read_bytes()
        before_mtime = os.stat(path).st_mtime

        memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )

        assert path.read_bytes() == before_bytes
        assert os.stat(path).st_mtime == before_mtime

    def test_a_real_run_does_persist(self, db_session, adopting_project):
        """The dry-run tests above would pass against a function that never
        writes at all. This is the positive that makes them meaningful."""
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        result = memory_adopt.enumerate_candidates(
            db_session, project, run, persist=True
        )
        db_session.flush()

        persisted = (
            db_session.query(MemoryTransition)
            .filter(MemoryTransition.project_id == project.id)
            .all()
        )
        assert len(persisted) == result.candidate_count > 0
        assert all(r.state == TransitionState.pending for r in persisted)
        # `direction` lives on the RUN now (DWB-593), stated once rather than
        # repeated on every entry. Assert the link instead, which is the thing
        # that would actually break: an entry with no run is the orphan the run
        # table exists to make impossible.
        assert all(r.run_id == run.id for r in persisted)
        assert run.direction == TransitionDirection.adopt
        # DWB-631: this used to assert `proposed_tier is None` on every row.
        # The column is GONE, so the rule it guarded is now structural rather
        # than asserted - there is no field a snapshot could put a proposal in.
        # An absence assertion holds until someone writes the line nobody
        # anticipated; an absent column cannot be written to at all.
        assert not hasattr(persisted[0], "proposed_tier"), (
            "proposed_tier is back; phase 1 is deterministic and makes no "
            "judgment, and tiering here would rubber-stamp in-the-moment salience"
        )


class TestEnumeratedAtBelongsToTheCaller:
    """DWB-593's BEGIN edge stamps `enumerated_at` after this returns.

    It was briefly stamped here too. Two writers for one ordering fact is the
    duplication this lane keeps ruling against, and the caller is the right
    owner because it also owns the run's state transition that follows.
    """

    def test_enumeration_does_not_stamp_the_run(self, db_session, adopting_project):
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        memory_adopt.enumerate_for_run(db_session, project=project, run=run)

        assert run.enumerated_at is None, (
            "enumeration stamped enumerated_at; DWB-593's BEGIN edge owns that "
            "and two writers for one ordering fact will drift"
        )

    def test_enumeration_does_not_touch_the_run_state(
        self, db_session, adopting_project
    ):
        from app.models.memory_transition import TransitionRunState

        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        memory_adopt.enumerate_for_run(db_session, project=project, run=run)

        assert run.state == TransitionRunState.open


class TestZeroIsCorroboratedAgainstTheSource:
    """THE HELD RULING. Zero candidates is a fact about the SPLITTER, not about
    the files, so it is corroborated before it is trusted.

    `memory_format`'s own measurement proves the risk is real: a bullet-only
    splitter returns ZERO for a 202-line file full of lessons. Cutting a project
    over on that reading seals a store whose agents genuinely have memory.

    "Nothing to adopt" and "found nothing in something" must never share a code
    path, and the second must be loud.
    """

    def test_genuinely_empty_files_return_zero_and_permit_cutover(
        self, db_session, make_project, make_agent, tmp_path
    ):
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="NeverWrote")
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        assert (
            memory_adopt.enumerate_for_run(db_session, project=project, run=run) == 0
        )

    def test_a_structure_only_file_returns_zero_and_permits_cutover(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """A fresh condense marker and a title really do hold no lessons."""
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="StructureOnly")
        _write_memory(
            tmp_path,
            project_dict["prefix"],
            "StructureOnly",
            "## 2026-09-29T12:00:00+00:00 - condensed\n# Memory - StructureOnly\n",
        )
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        assert (
            memory_adopt.enumerate_for_run(db_session, project=project, run=run) == 0
        )

    def test_content_that_yields_no_candidates_refuses_loudly(
        self, db_session, make_project, make_agent, tmp_path, monkeypatch
    ):
        """The case the ruling exists for, simulated by breaking the splitter.

        This is the only honest way to test it: the current splitter handles
        every shape in the corpus, so a fixture cannot produce the state. A
        FUTURE splitter bug can, and that is exactly what must not cut over.
        """
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="HasLessons")
        _write_memory(
            tmp_path, project_dict["prefix"], "HasLessons", SAMPLE
        )
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        from app.services import memory_format

        monkeypatch.setattr(
            memory_adopt.memory_format,
            "split",
            lambda text: memory_format.ParsedMemory(),
        )

        with pytest.raises(memory_adopt.EnumerationDefect) as exc:
            memory_adopt.enumerate_for_run(db_session, project=project, run=run)
        assert "HasLessons" in str(exc.value)
        assert "nothing to adopt" in str(exc.value)

    def test_an_unreadable_file_refuses_rather_than_returning_zero(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """Content we could not SEE is not content that is not there."""
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="Unreadable")
        path = _write_memory(
            tmp_path, project_dict["prefix"], "Unreadable", "- a real lesson\n"
        )
        os.chmod(path, 0o000)
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        try:
            if os.geteuid() == 0:  # pragma: no cover
                pytest.skip("running as root; chmod 000 does not deny access")
            with pytest.raises(memory_adopt.EnumerationDefect):
                memory_adopt.enumerate_for_run(db_session, project=project, run=run)
        finally:
            os.chmod(path, 0o644)

    def test_a_real_enumeration_returns_its_count(
        self, db_session, adopting_project
    ):
        """The positive that stops the refusals above passing against a function
        that refuses everything."""
        project_dict, _agent = adopting_project
        project = _project(db_session, project_dict)
        run = _run(db_session, project_dict)

        assert memory_adopt.enumerate_for_run(
            db_session, project=project, run=run
        ) == 3


class TestZeroCandidateStatesStayDistinguishable:
    """Three different facts that all count zero. Only one is benign."""

    def test_an_agent_who_never_wrote_is_counted_as_such(
        self, db_session, make_project, make_agent, tmp_path
    ):
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="NeverWrote")
        project = _project(db_session, project_dict)

        result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        assert result.is_empty
        assert result.agents_seen == 1
        assert result.agents_with_no_memory == 1
        assert result.unreadable == []

    def test_an_unreadable_file_is_not_counted_as_no_memory(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """The one that matters. A file skipped for an IO error looks exactly
        like a file with no lessons, and adopting past it silently drops that
        agent's memory at cutover."""
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="Unreadable")
        path = _write_memory(
            tmp_path, project_dict["prefix"], "Unreadable", "- a real lesson\n"
        )
        os.chmod(path, 0o000)
        project = _project(db_session, project_dict)

        try:
            result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        finally:
            os.chmod(path, 0o644)

        if os.geteuid() == 0:  # pragma: no cover - root ignores the mode bits
            pytest.skip("running as root; chmod 000 does not deny access")

        assert result.is_empty
        assert result.unreadable == [str(path)], result.unreadable
        assert result.agents_with_no_memory == 0, (
            "an unreadable file was counted as an agent with no memory; those "
            "two states must stay distinguishable or a cutover loses content"
        )

    def test_a_file_with_only_structure_yields_no_candidates(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """Provenance markers and a title are not lessons."""
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="StructureOnly")
        _write_memory(
            tmp_path,
            project_dict["prefix"],
            "StructureOnly",
            "## 2026-09-29T12:00:00+00:00 - condensed\n# Memory - StructureOnly\n",
        )
        project = _project(db_session, project_dict)

        result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        assert result.is_empty
        assert result.agents_with_no_memory == 1
        assert result.unreadable == []

    def test_a_project_with_no_agents_enumerates_empty(
        self, db_session, make_project, tmp_path
    ):
        project_dict = make_project(repo_path=str(tmp_path))
        project = _project(db_session, project_dict)
        result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        assert result.is_empty
        assert result.agents_seen == 0


class TestMultipleAgents:
    def test_every_agent_on_the_project_is_enumerated(
        self, db_session, make_project, make_agent, tmp_path
    ):
        project_dict = make_project(repo_path=str(tmp_path))
        a = make_agent(project_id=project_dict["id"], name="First")
        b = make_agent(project_id=project_dict["id"], name="Second")
        _write_memory(tmp_path, project_dict["prefix"], "First", "- lesson A\n")
        _write_memory(
            tmp_path, project_dict["prefix"], "Second", "- lesson B\n- lesson C\n"
        )
        project = _project(db_session, project_dict)

        result = memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        )
        assert result.agents_seen == 2
        assert result.candidate_count == 3
        by_agent = {}
        for row in result.rows:
            by_agent[row.agent_id] = by_agent.get(row.agent_id, 0) + 1
        assert by_agent == {a["id"]: 1, b["id"]: 2}

    def test_rows_are_grouped_by_agent_in_id_order(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """Determinism across agents, not just within one file."""
        project_dict = make_project(repo_path=str(tmp_path))
        a = make_agent(project_id=project_dict["id"], name="Alpha")
        b = make_agent(project_id=project_dict["id"], name="Beta")
        _write_memory(tmp_path, project_dict["prefix"], "Alpha", "- one\n")
        _write_memory(tmp_path, project_dict["prefix"], "Beta", "- two\n")
        project = _project(db_session, project_dict)

        ids = [
            r.agent_id
            for r in memory_adopt.enumerate_candidates(
            db_session, project, _run(db_session, project_dict), persist=False
        ).rows
        ]
        assert ids == sorted(ids)
        assert ids == [min(a["id"], b["id"]), max(a["id"], b["id"])]
