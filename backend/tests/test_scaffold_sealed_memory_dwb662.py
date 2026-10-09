# Path: tests/test_scaffold_sealed_memory_dwb662.py
# File: test_scaffold_sealed_memory_dwb662.py
# Created: 2026-10-08 (DWB-662)
# Purpose: Guard that the spawn scaffold does NOT create a sealed memory.md on
#          a human_memory project, still creates it on stock and adopting, and
#          never deletes one that already exists.
# Caller: pytest
# Callees: app.services.agent_memory.scaffold_agent_dir,
#          POST /api/agents, POST /api/agents/{id}/scaffold-memory
# Data In: tmp_path filesystem, factory projects + agents
# Data Out: Assertions on which files exist on disk after a scaffold
# Last Modified: 2026-10-08 (DWB-662)

"""DWB-662: a zero-byte memory.md on a sealed project reds a test forever.

WHAT WENT WRONG. The scaffold touched an empty `memory.md` for every new agent.
On a `human_memory` project that file is SEALED - every stock memory route
returns 409 at `app/routers/agents.py:408` before it reaches the filesystem -
so it could never gain content. `test_memory_format_dwb594.py::
test_headings_survive_as_context_not_as_entries` reads every live memory.md as
a corpus and requires a heading chain in each, so the file failed that test
permanently from the moment the agent spawned, and one more arrived with every
future spawn on DWB or IND.

The failure named a person and implicated nothing they did: Benny's spawn
created the file before he had made an edit, and the assertion quoted his name.

WHY THE FIX IS AT THE SCAFFOLD AND NOT AT THE TEST. The corpus test's CLAIM is
right - a memory.md should carry its heading chain - and its corpus was right
too, because every file in it is a real memory file. What was wrong was
creating a file that is not one. Excluding sealed files from the corpus would
have meant teaching a filesystem test to resolve each directory name to a
project's `memory_mode`, coupling it to DB state; excluding EMPTY files would
have been cheaper and worse, because it silently drops a file that was
truncated when it should have had content.

WHY AT THE SCAFFOLD AND NOT AT A CALLER: six call sites reach it
(`agent.create_agent` and two others, `project_agent` assign, the
scaffold-agents and scaffold-memory endpoints, and `playbook_deploy`), so a fix
at any one leaves five open.

THE THREE MODES ARE TESTED TOGETHER ON PURPOSE. `stock` and `adopting` must
still get the file and `human_memory` must not, and a test that checked only
the sealed case would pass just as happily against a scaffold that had stopped
creating memory.md for everybody.
"""

from pathlib import Path

from app.models.project import MemoryMode, Project


def _memory_dir(repo_path, prefix, name) -> Path:
    return Path(repo_path) / ".dwb" / "memory" / prefix / name


def _project(client, db_session, tmp_path, prefix, mode):
    r = client.post(
        "/api/projects",
        json={
            "prefix": prefix,
            "name": f"{prefix} scaffold",
            "repo_path": str(tmp_path),
            "force_handoff_md": False,
        },
    )
    assert r.status_code == 201, r.text
    project = r.json()
    if mode is not MemoryMode.stock:
        row = db_session.get(Project, project["id"])
        row.memory_mode = mode
        db_session.flush()
    return project


def _agent(client, project_id, name):
    r = client.post(
        "/api/agents",
        json={
            "project_id": project_id,
            "name": name,
            "role": "developer",
            "api_key": f"key-{name}",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestASealedProjectGetsNoMemoryFile:
    """AC: a spawn on human_memory leaves no file behind to fail the corpus."""

    def test_the_three_modes_differ_in_the_stated_direction(
        self, client, db_session, tmp_path
    ):
        """All three in one test, because the interesting property is the
        DIFFERENCE.

        A test that only checked the sealed case would pass against a scaffold
        that had stopped writing memory.md for every project, which would break
        stock mode silently - the file is the agent's actual memory there.
        """
        cases = [
            ("SEAL", MemoryMode.human_memory, False),
            ("STCK", MemoryMode.stock, True),
            ("ADPT", MemoryMode.adopting, True),
        ]
        seen = {}
        for prefix, mode, expected in cases:
            root = tmp_path / prefix
            root.mkdir()
            project = _project(client, db_session, root, prefix, mode)
            _agent(client, project["id"], f"Probe{prefix}")
            path = _memory_dir(root, prefix, f"Probe{prefix}") / "memory.md"
            seen[mode.value] = path.exists()
            # identity.md is system-generated and must exist in every mode -
            # asserted so "memory.md is absent" cannot pass because the
            # scaffold did nothing at all.
            assert (
                _memory_dir(root, prefix, f"Probe{prefix}") / "identity.md"
            ).exists(), f"{prefix}: the scaffold did not run; the check below is vacuous"
            assert path.exists() is expected, (
                f"{prefix} ({mode.value}): memory.md exists={path.exists()}, "
                f"expected {expected}"
            )
        assert seen == {
            "human_memory": False,
            "stock": True,
            "adopting": True,
        }, seen

    def test_adopting_keeps_the_file_because_it_is_the_source(
        self, client, db_session, tmp_path
    ):
        """Mid-adoption the stock file is being READ, not ignored.

        `memory_adopt` snapshots and splits memory.md to produce the entries an
        agent then tiers. Withholding it during `adopting` would break the
        migration the mode exists to perform, so `adopting` is deliberately
        outside the seal even though the project is on its way to
        human_memory.
        """
        project = _project(client, db_session, tmp_path, "ADP2", MemoryMode.adopting)
        _agent(client, project["id"], "ProbeAdopting")
        assert (
            _memory_dir(tmp_path, "ADP2", "ProbeAdopting") / "memory.md"
        ).exists()


class TestAnExistingFileIsNeverRemoved:
    """The fix changes what is CREATED and must never change what is there."""

    def test_a_populated_memory_file_survives_a_re_scaffold_on_a_sealed_project(
        self, client, db_session, tmp_path
    ):
        """The dangerous version of this fix deletes rather than withholds.

        An agent that carried real memory from before the project was sealed -
        every pre-existing DWB agent does, 9KB to 19KB each - must not have it
        removed by a scaffold run. Asserted byte-for-byte, not just by
        existence.
        """
        project = _project(client, db_session, tmp_path, "KEEP", MemoryMode.stock)
        agent = _agent(client, project["id"], "ProbeKeep")
        path = _memory_dir(tmp_path, "KEEP", "ProbeKeep") / "memory.md"
        assert path.exists()
        content = "## 2026-10-08T00:00:00+00:00 - condensed\n\n## Lessons\nreal content\n"
        path.write_text(content, encoding="utf-8")

        # Seal the project AFTER the file exists, which is the real sequence
        # for every agent that predates the mode switch.
        row = db_session.get(Project, project["id"])
        row.memory_mode = MemoryMode.human_memory
        db_session.flush()

        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200, r.text

        assert path.exists(), "a re-scaffold on a sealed project DELETED a real file"
        assert path.read_text(encoding="utf-8") == content
        assert str(path) in r.json()["preserved"]


class TestTheWithholdingIsReported:
    """A shorter `created` list must have a stated reason, not just be shorter."""

    def test_not_created_names_the_withheld_file(
        self, client, db_session, tmp_path
    ):
        project = _project(client, db_session, tmp_path, "RPT", MemoryMode.human_memory)
        agent = _agent(client, project["id"], "ProbeReport")

        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200, r.text
        body = r.json()

        assert "not_created" in body, (
            "the endpoint dropped the field. A scaffold that withholds a file "
            "and reports nothing is the silent-omission shape this ticket is "
            "about, one layer out."
        )
        assert [Path(p).name for p in body["not_created"]] == ["memory.md"]
        assert body["created"] == []

    def test_a_stock_project_reports_nothing_withheld(
        self, client, db_session, tmp_path
    ):
        """The other half. `not_created` non-empty everywhere would carry no
        information."""
        project = _project(client, db_session, tmp_path, "RPT2", MemoryMode.stock)
        agent = _agent(client, project["id"], "ProbeReport2")

        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200, r.text
        assert r.json()["not_created"] == []
