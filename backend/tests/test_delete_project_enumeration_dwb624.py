# Path: tests/test_delete_project_enumeration_dwb624.py
# File: test_delete_project_enumeration_dwb624.py
# Created: 2026-10-01
# Purpose: DWB-624 (absorbing DWB-616) - delete_project must clear EVERY child
#          table that blocks the teardown, not the two that prompted the
#          ticket. Covers the four direct project_id gaps (node_pointers,
#          nodes, node_exclusions, standards_audit), the two reachable only
#          through dwb_sessions (agent_memories, journal_entries), and a
#          mechanical guard so a child table added later cannot escape.
# Caller: pytest
# Callees: DELETE /api/projects/{id}, app.services.project.delete_project
# Data In: Factory-created projects/agents via conftest fixtures
# Data Out: Assertions on the delete response and surviving rows

import inspect
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import Base
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.journal_entry import JournalEntry
from app.models.node import Node, NodePointer, NodePointerKind
from app.models.node_exclusion import NodeExclusion
from app.models.standards_audit import AuditVerdict, StandardsAudit
from app.services.project import delete_project

# The tables this ticket found unhandled. Named explicitly so that the
# mechanical guard below cannot pass by discovering nothing: a pattern that
# matches an empty set satisfies every assertion made over it.
KNOWN_BLOCKING_CHILDREN = {
    "node_pointers",
    "nodes",
    "node_exclusions",
    "standards_audit",
    "memory_transitions",
    "memory_transition_runs",
    "tracking_log",
    "test_results",
    "hook_sessions",
    "dwb_sessions",
    "sprints",
    "epics",
    "tickets",
}


def _seed_every_blocking_child(db_session, pid, aid):
    """Put a row in each table that previously blocked the teardown.

    Returns the dwb_session id, which is how agent_memories and
    journal_entries reach the project: neither carries a project_id column.
    """
    db_session.add(NodeExclusion(project_id=pid, pattern="probe/*"))
    node = Node(project_id=pid, tag="probe", weight=1)
    db_session.add(node)
    db_session.flush()
    db_session.add(
        NodePointer(
            project_id=pid,
            node_id=node.id,
            tag="probe",
            kind=NodePointerKind.code,
            ref="probe.py",
        )
    )
    db_session.add(
        StandardsAudit(project_id=pid, pr_ref="probe-pr", verdict=AuditVerdict.passed)
    )
    # opened_at is NOT NULL and the create_all schema carries no server default
    # for it, so it is set here rather than left to the database.
    session = DwbSession(
        project_id=pid,
        open_method=DwbOpenMethod.slash,
        opened_at=datetime.now(timezone.utc),
    )
    db_session.add(session)
    db_session.flush()
    db_session.add(
        AgentMemory(
            agent_id=aid,
            tier=MemoryTier.scar,
            body="a lesson that must outlive the project",
            created_session_id=session.id,
            last_reinforced_session_id=session.id,
        )
    )
    db_session.add(
        JournalEntry(agent_id=aid, body="journal body", dwb_session_id=session.id)
    )
    db_session.flush()
    return session.id


class TestDeleteProjectFullEnumeration:
    """The defect is the ENUMERATION, not any one table.

    Against the pre-fix code a fully populated project needed five DELETE
    calls, each clearing the single table the previous error named. That is
    what made it expensive: the operator is handed a different error every
    time and stops trusting the error text. The outcome that captures it is
    the ATTEMPT COUNT, not the error string.
    """

    def test_project_with_every_blocking_child_deletes_in_one_attempt(
        self, client, make_project, make_agent, db_session
    ):
        project = make_project()
        pid = project["id"]
        agent = make_agent(project_id=pid)
        aid = agent["id"]
        _seed_every_blocking_child(db_session, pid, aid)
        db_session.commit()

        attempts = 0
        status = None
        for _ in range(8):
            attempts += 1
            status = client.delete(f"/api/projects/{pid}").status_code
            if status == 204:
                break

        # Against the pre-fix code this never reaches 204 at all: nothing is
        # cleared between attempts, so every call fails on the first missing
        # table. The five-errors-in-a-row sequence that made this expensive to
        # diagnose only appears when an operator clears the table each error
        # names and retries, which is what the manual reproduction did.
        assert status == 204
        # The attempt count, not the error text, is the outcome worth pinning:
        # a test asserting only "eventually 204" would pass against a teardown
        # that still needed several calls.
        assert attempts == 1, (
            f"took {attempts} delete calls; each extra call is a child table "
            "the teardown did not know about"
        )
        assert client.get(f"/api/projects/{pid}").status_code == 404

    def test_agent_memory_survives_and_only_the_session_link_is_cleared(
        self, client, make_project, make_agent, db_session
    ):
        """Memory belongs to the AGENT, not to the project.

        delete_project detaches agents rather than deleting them, because a
        name is unique system-wide and an agent may carry history elsewhere.
        Their memory follows the same rule: nulling the session reference
        drops only the linkage that is genuinely going away. Deleting the
        rows would lose lessons because an unrelated project was removed.
        """
        project = make_project()
        pid = project["id"]
        agent = make_agent(project_id=pid)
        aid = agent["id"]
        sid = _seed_every_blocking_child(db_session, pid, aid)
        db_session.commit()

        assert client.delete(f"/api/projects/{pid}").status_code == 204
        db_session.expire_all()

        memories = db_session.scalars(
            select(AgentMemory).where(AgentMemory.agent_id == aid)
        ).all()
        journals = db_session.scalars(
            select(JournalEntry).where(JournalEntry.agent_id == aid)
        ).all()

        assert len(memories) == 1, "the agent's lesson was destroyed with the project"
        assert memories[0].created_session_id is None
        assert memories[0].last_reinforced_session_id is None

        # Two journal entries now, not one: the seeded entry survives, and the
        # teardown adds an origin-lost entry because this memory's only
        # origins were on the deleted project, so it loses scoreability and
        # hard rule 4 requires it land in the journal before that happens.
        assert len(journals) == 2, (
            "expected the seeded entry plus the origin-lost entry the teardown "
            f"writes; got {[j.body for j in journals]}"
        )
        seeded = [j for j in journals if j.body == "journal body"]
        origin_lost = [j for j in journals if "origin-lost" in (j.tags or [])]
        assert len(seeded) == 1, "the agent's pre-existing journal entry was destroyed"
        assert len(origin_lost) == 1, "the memory losing its clock was not journalled"
        assert all(j.dwb_session_id is None for j in journals), (
            "every journal reference to the deleted project's sessions must be "
            "cleared, including the entry the teardown itself just wrote"
        )
        assert (
            db_session.get(DwbSession, sid) is None
        ), "the session itself should be gone"


class TestOriginLossIsJournalledFirst:
    """Hard rule 4: nothing leaves memory without landing in the journal first.

    Nulling both origins makes a row unscoreable, and an unscoreable row is
    excluded from every candidate list and never rendered again. The row
    survives in the table but has effectively left memory, so it is journalled
    before the nulling, carrying its ORIGINAL date rather than the date the
    project happened to be deleted.
    """

    def _seed(self, db_session, aid, doomed_sid, surviving_sid):
        original = datetime(2026, 1, 15, 9, 0, 0)
        rows = [
            ("scar both origins doomed", MemoryTier.scar, doomed_sid, doomed_sid),
            ("scar reinforced elsewhere", MemoryTier.scar, doomed_sid, surviving_sid),
        ]
        for body, tier, created, reinforced in rows:
            db_session.add(
                AgentMemory(
                    agent_id=aid,
                    tier=tier,
                    body=body,
                    created_session_id=created,
                    last_reinforced_session_id=reinforced,
                    created_at=original,
                )
            )
        db_session.flush()
        return original

    def test_a_memory_losing_its_clock_is_journalled_with_its_original_date(
        self, client, make_project, make_agent, db_session
    ):
        doomed = make_project()
        survivor = make_project()
        agent = make_agent(project_id=survivor["id"])
        aid = agent["id"]
        doomed_session = DwbSession(
            project_id=doomed["id"],
            open_method=DwbOpenMethod.slash,
            opened_at=datetime.now(timezone.utc),
        )
        surviving_session = DwbSession(
            project_id=survivor["id"],
            open_method=DwbOpenMethod.slash,
            opened_at=datetime.now(timezone.utc),
        )
        db_session.add_all([doomed_session, surviving_session])
        db_session.flush()
        original = self._seed(
            db_session, aid, doomed_session.id, surviving_session.id
        )
        db_session.commit()

        assert client.delete(f"/api/projects/{doomed['id']}").status_code == 204
        db_session.expire_all()

        entries = db_session.scalars(
            select(JournalEntry).where(JournalEntry.agent_id == aid)
        ).all()
        bodies = [e.body for e in entries]

        # Exactly the row that lost its clock, and only that row.
        assert bodies == ["scar both origins doomed"], (
            "journalled the wrong set: a row reinforced on a surviving project "
            "keeps that origin through the COALESCE and is not leaving memory"
        )
        assert entries[0].created_at == original, (
            "the journal entry must carry the memory's ORIGINAL date, not the "
            "date the project was deleted"
        )
        assert "origin-lost" in (entries[0].tags or [])

    def test_a_memory_reinforced_elsewhere_keeps_its_clock(
        self, client, make_project, make_agent, db_session
    ):
        doomed = make_project()
        survivor = make_project()
        agent = make_agent(project_id=survivor["id"])
        aid = agent["id"]
        doomed_session = DwbSession(
            project_id=doomed["id"],
            open_method=DwbOpenMethod.slash,
            opened_at=datetime.now(timezone.utc),
        )
        surviving_session = DwbSession(
            project_id=survivor["id"],
            open_method=DwbOpenMethod.slash,
            opened_at=datetime.now(timezone.utc),
        )
        db_session.add_all([doomed_session, surviving_session])
        db_session.flush()
        self._seed(db_session, aid, doomed_session.id, surviving_session.id)
        surviving_id = surviving_session.id
        db_session.commit()

        assert client.delete(f"/api/projects/{doomed['id']}").status_code == 204
        db_session.expire_all()

        kept = db_session.scalars(
            select(AgentMemory).where(
                AgentMemory.agent_id == aid,
                AgentMemory.body == "scar reinforced elsewhere",
            )
        ).one()
        assert kept.created_session_id is None, "the doomed origin must be cleared"
        assert kept.last_reinforced_session_id == surviving_id, (
            "an origin on a surviving project must not be cleared; clearing it "
            "is what makes the row unscoreable and is the whole defect"
        )


class TestDeleteProjectEnumerationGuard:
    """A table added later must not be able to escape the teardown quietly.

    Discovery is by FK rather than by a hand-written list, so a child added
    after this test was written is still covered. The non-empty assertion
    names what the discovery must find, because a pattern that matches
    nothing satisfies every assertion made over it.
    """

    @staticmethod
    def _blocking_child_tables():
        blocking = set()
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                if fk.column.table.name != "projects":
                    continue
                # SET NULL and CASCADE resolve themselves at the database.
                # Only NO ACTION (ondelete unset) blocks the parent delete.
                if (fk.ondelete or "").upper() in {"SET NULL", "CASCADE"}:
                    continue
                blocking.add(table.name)
        return blocking

    def test_discovery_finds_the_known_children(self):
        found = self._blocking_child_tables()
        missing = KNOWN_BLOCKING_CHILDREN - found
        assert not missing, (
            "the FK discovery stopped finding tables it is supposed to cover: "
            f"{sorted(missing)}. Fix the discovery, not this list."
        )

    def test_every_blocking_child_is_handled_in_delete_project(self):
        source = inspect.getsource(delete_project)
        table_to_class = {
            mapper.class_.__tablename__: mapper.class_.__name__
            for mapper in Base.registry.mappers
        }
        unhandled = []
        for table in sorted(self._blocking_child_tables()):
            cls = table_to_class.get(table)
            # No mapped class at all is itself a gap worth failing on, rather
            # than a table silently skipped because the lookup missed.
            if cls is None or not re.search(rf"\b{re.escape(cls)}\b", source):
                unhandled.append(table)
        assert not unhandled, (
            "delete_project does not clear these child tables, so deleting a "
            f"project that has rows in them 500s: {unhandled}"
        )

    def test_the_guard_would_notice_a_missing_table(self):
        """Positive control, so a green above means something.

        The detection is run against a source string with one known child
        deliberately absent. If this does not go red, the guard is matching
        on something other than what it claims and every pass it reports is
        uninformative. Done against a string rather than by editing the real
        module, because mutating a shared working tree makes it deliberately
        wrong for anyone else measuring it at the same moment.
        """
        real = inspect.getsource(delete_project)
        assert "NodeExclusion" in real, "fixture assumption broke; update this test"
        doctored = real.replace("NodeExclusion", "SomethingElseEntirely")

        table_to_class = {
            mapper.class_.__tablename__: mapper.class_.__name__
            for mapper in Base.registry.mappers
        }
        unhandled = [
            table
            for table in sorted(self._blocking_child_tables())
            if (cls := table_to_class.get(table)) is None
            or not re.search(rf"\b{re.escape(cls)}\b", doctored)
        ]
        assert "node_exclusions" in unhandled, (
            "the guard did not notice a child table being dropped from the "
            "teardown, so its passing verdict carries no information"
        )

    def test_session_linked_memory_tables_are_handled(self):
        """agent_memories and journal_entries carry NO project_id.

        They cannot appear in an enumeration of tables referencing `projects`,
        which is exactly why they were missed: counting project_id columns
        finds four of the six gaps and reports itself complete.
        """
        source = inspect.getsource(delete_project)
        for name in ("AgentMemory", "JournalEntry"):
            assert re.search(rf"\b{name}\b", source), (
                f"{name} reaches the project only through dwb_sessions and "
                "blocks that delete; it must be cleared before the sessions go"
            )
