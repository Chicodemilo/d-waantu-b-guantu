# Path: tests/test_persistence_instrument_dwb653.py
# File: test_persistence_instrument_dwb653.py
# Created: 2026-10-08 (DWB-653)
# Purpose: Prove the persistence instrument actually measures persistence -
#          both controls, then the AC1 demonstration that a route with its
#          commit removed turns a test RED where the old harness stayed green.
# Caller: pytest
# Callees: tests/persistence_instrument.py, POST /api/agents/{id}/memories/
#          {mid}/withdraw, app.routers.agents
# Data In: real committed rows in lat_test
# Data Out: Assertions read down a second, independent connection
# Last Modified: 2026-10-08 (DWB-653)

"""Does the instrument measure the thing, or does it measure itself?

THE TRAP THIS FILE IS BUILT AROUND. An instrument for "did it persist" is
worthless if its reader can see uncommitted rows, and a reader that sees
NOTHING passes an "it did not persist" assertion for any reason at all,
including being pointed at the wrong database. So the first two tests are
CONTROLS IN OPPOSITE DIRECTIONS, and neither alone would do:

  - `test_the_readback_connection_cannot_see_uncommitted_work` writes through
    the ORDINARY harness and asserts the reader sees nothing. That is the
    negative control, and it is also the clearest statement of DWB-653 itself:
    the ordinary client's writes never reach disk.
  - `test_the_readback_connection_does_see_committed_work` writes through the
    PERSISTING harness and asserts the reader sees it. Without this one, the
    test above would pass just as happily against a reader connected to an empty
    database, a wrong schema, or nothing at all.

Only once both hold does the AC1 demonstration below mean anything.

AC1 IS A BREAK/RESTORE AND IT IS NOT RUN FROM INSIDE THIS FILE. A test that
mutates application source mid-run is a tripwire for whoever else is in the
tree, and in a shared checkout that is indistinguishable from a bug to the
person who hits it. The break, the red, the restore and the `cmp` are performed
from the shell and recorded in the ticket. What lives here permanently is the
ASSERTION that goes red when the commit is gone - `test_a_withdrawn_memory_is
_really_gone` - plus `test_the_same_claim_under_the_old_harness_proves_nothing`,
which runs the ordinary harness beside it on the same operation and shows that
it cannot tell the difference. That pair is the permanent version of the
demonstration.
"""

from app.models.agent_memory import AgentMemory
from app.models.journal_entry import JournalEntry
from app.models.project import MemoryMode, Project
from tests.persistence_instrument import Readback
from tests.conftest import MEMORY_WRITE_EXTRAS


def _human_memory_project(client, session_for_mode, prefix):
    """A project in human_memory mode, created through `client`.

    `session_for_mode` is a RAW session, because memory_mode is not settable
    through the API without the confirmation flag and this flips the column
    directly. Under the persisting fixture, pass `readback.session` - the
    property discards the snapshot before handing it over.
    """
    r = client.post(
        "/api/projects",
        json={"prefix": prefix, "name": f"{prefix} persistence", "force_handoff_md": False},
    )
    assert r.status_code == 201, r.text
    project = r.json()
    row = session_for_mode.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    session_for_mode.commit()
    return project


def _agent_with_memory(client, project_id, body="a lesson to retract"):
    agent = client.post(
        "/api/agents",
        json={
            "project_id": project_id,
            "name": f"PersistProbe{project_id}",
            "role": "developer",
            "api_key": f"persist-key-{project_id}",
        },
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    opened = client.post(
        "/api/sessions/open",
        json={"project_id": project_id, "open_method": "slash"},
    )
    assert opened.status_code == 201, opened.text

    written = client.post(f"/api/agents/{agent_id}/memories", json={**MEMORY_WRITE_EXTRAS, "body": body})
    assert written.status_code == 201, written.text
    return agent_id, written.json()["id"]


class TestTheInstrumentMeasuresPersistence:
    """Both controls. Run these before believing anything else in this file."""

    def test_the_readback_connection_cannot_see_uncommitted_work(
        self, client, session_factory_
    ):
        """The negative control, and a direct statement of DWB-653.

        A project is created through the ORDINARY client - the one 3000 tests
        use - and a second, independent session cannot find it, because the
        ordinary harness never commits. The ordinary client is asserted to
        BELIEVE it worked first, so this cannot pass merely because the POST
        failed.
        """
        r = client.post(
            "/api/projects",
            json={"prefix": "UNCOMMIT", "name": "never reaches disk"},
        )
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        # The ordinary harness is perfectly happy: it reads its own write back.
        assert client.get(f"/api/projects/{project_id}").status_code == 200

        reader = Readback(session_factory_())
        try:
            assert reader.get(Project, project_id) is None, (
                "a second connection can see the ordinary harness's writes. "
                "Either the harness now commits - in which case DWB-653 may be "
                "fixed and this instrument is redundant - or the reader is not "
                "actually on an independent transaction, in which case every "
                "persistence claim in this file is void."
            )
        finally:
            reader.close()

    def test_the_readback_connection_does_see_committed_work(self, persisting):
        """The positive control. Without it the test above passes against a
        reader pointed at nothing."""
        client, readback = persisting
        r = client.post(
            "/api/projects",
            json={"prefix": "COMMITD", "name": "really lands"},
        )
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        found = readback.get(Project, project_id)
        assert found is not None, (
            "the persisting fixture did not actually commit, so this whole file "
            "is measuring nothing"
        )
        assert found.prefix == "COMMITD"


class TestTheACOneDemonstration:
    """The assertion that goes red when a route's commit is removed."""

    def test_a_withdrawn_memory_is_really_gone(self, persisting):
        """DWB-652's route, asserted through the instrument.

        This is the test the break/restore in the ticket turns red. With the
        commit present the memory is gone and the journal entry exists, read
        down a connection that can only see committed rows. With the commit
        removed, the route still answers 200 and the memory is still there.

        The journal entry is asserted as well as the deletion, and deliberately:
        hard rule 4 says anything leaving memory lands in the journal FIRST, so
        "the row is gone" alone would pass against a withdrawal that destroyed
        the lesson instead of moving it.
        """
        client, readback = persisting
        project = _human_memory_project(client, readback.session, "WDRAW")
        agent_id, memory_id = _agent_with_memory(client, project["id"])

        # Present on disk before the withdrawal, so the absence below is a
        # change rather than a state that was always true.
        assert readback.get(AgentMemory, memory_id) is not None, (
            "the memory never reached disk, so withdrawing it proves nothing"
        )

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/withdraw",
            json={"reason": "DWB-653 instrument demonstration"},
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 200, r.text
        journal_id = r.json()["journal_entry_id"]

        # No expire/refresh dance needed: every Readback accessor discards its
        # snapshot first. That is deliberate - under REPEATABLE READ a reader
        # that had already touched this row would keep reporting it present
        # after another transaction deleted and committed it, which is
        # indistinguishable from the bug being hunted.
        assert readback.get(AgentMemory, memory_id) is None, (
            "the withdraw route returned 200 and the memory is STILL on disk - "
            "the route did not commit. This is exactly DWB-652, and the old "
            "harness could not see it."
        )
        entry = readback.get(JournalEntry, journal_id)
        assert entry is not None, (
            f"the response named journal entry {journal_id} and no such row is "
            "on disk - the id was allocated inside a transaction that was "
            "discarded"
        )
        assert "withdrawn" in entry.tags

    def test_the_same_claim_under_the_old_harness_proves_nothing(
        self, client, db_session, session_factory_
    ):
        """The broken instrument beside the working one, permanently.

        This runs the ordinary harness over the same operation and asserts the
        OUTCOME IS AMBIGUOUS: the route answers 200 and the shared session says
        the memory is gone, while an independent connection says nothing ever
        landed - including the memory itself. That is not a bug being caught,
        it is the harness being unable to distinguish, and it is the reason
        DWB-652 shipped green.

        It asserts the DEFECT, so it will fail the day the ordinary harness
        starts committing. Whoever is holding it then should delete it.
        """
        project = _human_memory_project(client, db_session, "OLDHRN")
        agent_id, memory_id = _agent_with_memory(client, project["id"])

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/withdraw",
            json={"reason": "same call, blind instrument"},
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 200, r.text

        # The shared session is satisfied.
        assert db_session.get(AgentMemory, memory_id) is None

        # An independent connection never saw any of it - not the withdrawal,
        # and not the memory that preceded it.
        reader = Readback(session_factory_())
        try:
            assert reader.get(AgentMemory, memory_id) is None
            assert reader.get(Project, project["id"]) is None, (
                "the ordinary harness committed something; if that is now true "
                "this test and the instrument it justifies should both go"
            )
        finally:
            reader.close()


class TestTheCommitCensus:
    """The cheap instrument. Sound in the negative only, and labelled so."""

    def test_a_read_request_records_no_commit(self, client):
        from tests import persistence_instrument as pi

        before = len(pi.CENSUS)
        client.get("/api/status")
        assert len(pi.CENSUS) == before + 1, "the census did not record the request"
        row = pi.CENSUS[-1]
        assert row["method"] == "GET"
        assert row["commits"] == 0

    def test_a_write_request_that_commits_records_it(self, client):
        from tests import persistence_instrument as pi

        r = client.post(
            "/api/projects", json={"prefix": "CENSUS", "name": "census probe"}
        )
        assert r.status_code == 201, r.text
        row = pi.CENSUS[-1]
        assert row["method"] == "POST"
        assert row["status"] == 201
        assert row["commits"] >= 1, (
            "a 201 write recorded zero commits; either the census is not "
            "wrapping Session.commit or this route does not persist"
        )

    def test_the_census_distinguishes_the_two(self, client):
        """The discrimination, in one test, on one fixture.

        A count that is the same for a read and for a write is not measuring
        commits. Asserted as a comparison rather than as two separate
        thresholds, because two thresholds can both be met by a constant.
        """
        from tests import persistence_instrument as pi

        client.get("/api/status")
        read_row = pi.CENSUS[-1]
        client.post("/api/projects", json={"prefix": "DISCRIM", "name": "probe"})
        write_row = pi.CENSUS[-1]

        assert read_row["commits"] == 0
        assert write_row["commits"] > read_row["commits"]


def test_the_truncate_cost_is_bounded(persisting):
    """The price of the opt-in fixture, as a number rather than a worry.

    Not an assertion about a wall-clock threshold - that would be flaky on a
    loaded machine and would fail for reasons that have nothing to do with the
    code. It asserts only that the fixture completed and left a usable database,
    which is the correctness claim; the timing is measured from the shell and
    reported in the ticket.
    """
    client, readback = persisting
    r = client.post("/api/projects", json={"prefix": "COST", "name": "cost probe"})
    assert r.status_code == 201
    assert readback.get(Project, r.json()["id"]) is not None
