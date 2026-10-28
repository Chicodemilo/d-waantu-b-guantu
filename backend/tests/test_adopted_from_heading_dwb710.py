# Path: tests/test_adopted_from_heading_dwb710.py
# File: test_adopted_from_heading_dwb710.py
# Created: 2026-10-28 (DWB-710)
# Purpose: Guard the provenance move - that the migration's selection rule
#          moves adopted rows and ONLY adopted rows, that the value reaches a
#          reader, and that the scan never treats provenance as a scope.
# Caller: pytest
# Callees: the dwb710 migration's own SQL, GET /api/agents/{id}/memory/scored,
#          app.services.memory_scan.scan_context
# Data In: rows built through the factory fixtures
# Data Out: Assertions on which rows moved, on the served response, and on the
#           scan's inputs
# Last Modified: 2026-10-28 (DWB-710)

"""DWB-710.

`memory_decide.decide` wrote the markdown heading path of each adopted
`memory.md` section into `context_key` - a document location in the column the
SCAN reads as a scope. The value is false as a scope and true as provenance,
and the pipeline that produced it will never run again, so it was moved rather
than dropped.

THE SELECTION RULE IS THE WHOLE RISK, which is why it is tested before
anything else here. 425 scars carried a key and only 380 came from adoption;
the other 45, plus 23 WORKING rows, were authored by hand through
`raw_memory.append_raw_memory` and never came from a `memory.md`. Moving those
under a field named `adopted_from_heading` would state something false about
where they came from - the same category error the move exists to end, pointing
the other way. The two populations are INDISTINGUISHABLE BY THE STRING; only
the `memory_transitions` link separates them.

So `test_an_authored_key_is_left_alone` is the test that matters. A migration
that moved everything would pass every other assertion in this file.

THE MIGRATION'S SQL IS IMPORTED, NOT RETYPED. A copy of the predicate here
could drift from the one that ran and would then be testing a statement nobody
executes - and it would keep passing while the real rule changed underneath.
"""

import importlib.util
import pathlib

import pytest
from sqlalchemy import select

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.services import memory_scan

_MIGRATION = pathlib.Path(__file__).resolve().parent.parent / (
    "alembic/versions/dwb710a1b2c3_adopted_from_heading.py"
)


def _migration_module():
    """The real migration, loaded so its SQL is the SQL under test."""
    spec = importlib.util.spec_from_file_location("dwb710_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEADING = "THE ONE RULE, AND THE THREE WAYS IT BREAKS / 1. CLOSED LOOP"


@pytest.fixture
def owner(db_session, make_project, make_agent):
    project = make_project(memory_mode="human_memory")
    agent = make_agent(project_id=project["id"])
    # A real run row: `memory_transitions.run_id` is a FK, so an adopted row
    # cannot be faked without the adoption it belongs to.
    run = MemoryTransitionRun(
        project_id=project["id"],
        direction=TransitionDirection.adopt,
        state=TransitionRunState.completed,
    )
    db_session.add(run)
    db_session.flush()
    return {"project_id": project["id"], "agent_id": agent["id"], "run_id": run.id}


def _scar(db_session, owner, key, *, adopted):
    row = AgentMemory(
        agent_id=owner["agent_id"],
        tier=MemoryTier.scar,
        body=f"a lesson filed under {key}",
        condensed="a lesson",
        keywords=["sprint close", "backlog ticket"],
        context_key=key,
    )
    db_session.add(row)
    db_session.flush()
    if adopted:
        # What `memory_decide.decide` leaves behind, and the only thing that
        # distinguishes an adopted row from an authored one.
        db_session.add(
            MemoryTransition(
                project_id=owner["project_id"],
                agent_id=owner["agent_id"],
                run_id=owner["run_id"],
                state=TransitionState.written,
                source_excerpt=row.body,
                target_memory_id=row.id,
            )
        )
        db_session.flush()
    return row


class TestTheSelectionRule:
    def test_an_adopted_key_moves_to_provenance(self, db_session, owner):
        row = _scar(db_session, owner, HEADING, adopted=True)

        db_session.execute(_migration_module()._MOVE)
        db_session.expire_all()

        moved = db_session.get(AgentMemory, row.id)
        assert moved.adopted_from_heading == HEADING
        assert moved.context_key is None

    def test_an_authored_key_is_left_alone(self, db_session, owner):
        """THE ONE THAT MATTERS. Same string, same tier, no transition row.

        45 scars and 23 WORKING rows look exactly like an adopted row in this
        column and did not come from a `memory.md`. A migration that moved
        them would pass every other test here.
        """
        row = _scar(db_session, owner, HEADING, adopted=False)

        db_session.execute(_migration_module()._MOVE)
        db_session.expire_all()

        untouched = db_session.get(AgentMemory, row.id)
        assert untouched.context_key == HEADING, (
            "an authored context_key was moved into adopted_from_heading; that "
            "states something false about where the lesson came from"
        )
        assert untouched.adopted_from_heading is None

    def test_no_row_ever_carries_both(self, db_session, owner):
        """The move is a move. A row holding both would mean the scope column
        still carries a value the provenance column also claims."""
        _scar(db_session, owner, HEADING, adopted=True)
        _scar(db_session, owner, "Verification discipline", adopted=False)

        db_session.execute(_migration_module()._MOVE)
        db_session.expire_all()

        both = db_session.execute(
            select(AgentMemory).where(
                AgentMemory.context_key.isnot(None),
                AgentMemory.adopted_from_heading.isnot(None),
            )
        ).scalars().all()
        assert both == []

    def test_the_downgrade_puts_it_back(self, db_session, owner):
        """The data is moved, never dropped. This is the real safety net - a
        snapshot file is one accident from gone, a reverse is runnable."""
        row = _scar(db_session, owner, HEADING, adopted=True)
        module = _migration_module()

        db_session.execute(module._MOVE)
        db_session.expire_all()
        assert db_session.get(AgentMemory, row.id).context_key is None

        db_session.execute(module._RESTORE)
        db_session.expire_all()

        back = db_session.get(AgentMemory, row.id)
        assert back.context_key == HEADING
        assert back.adopted_from_heading is None


class TestTheReaderCanStillAnswerIt:
    def test_the_endpoint_serves_the_field(self, client, db_session, owner):
        """Declared in `ScoredMemoryEntry` or it never reaches a caller:
        pydantic's default `extra` is `ignore`, so a key the service sets and
        the model omits is stripped silently, with no error at any layer. That
        is the failure this project has already been bitten by twice."""
        row = _scar(db_session, owner, HEADING, adopted=True)
        db_session.execute(_migration_module()._MOVE)
        db_session.commit()

        r = client.get(f"/api/agents/{owner['agent_id']}/memory/scored")
        assert r.status_code == 200, r.text
        entry = next(e for e in r.json()["entries"] if e["id"] == row.id)

        assert entry["adopted_from_heading"] == HEADING
        assert entry["context_key"] is None

    def test_a_non_adopted_row_serves_null_rather_than_omitting_the_key(
        self, client, db_session, owner
    ):
        """Null is the correct answer for a lesson nobody adopted, and it has
        to be SAID. An absent key cannot be told from a field that was dropped
        on the way out."""
        row = _scar(db_session, owner, HEADING, adopted=False)
        db_session.commit()

        r = client.get(f"/api/agents/{owner['agent_id']}/memory/scored")
        entry = next(e for e in r.json()["entries"] if e["id"] == row.id)

        assert "adopted_from_heading" in entry
        assert entry["adopted_from_heading"] is None


class TestRemovalDoesNotDestroyProvenance:
    """`memory_removal.journal_and_remove` NULLs the `memory_transitions` link
    and then deletes the row. That link is the only witness that a lesson came
    through adoption - it is what the migration used to decide membership,
    because the heading string cannot distinguish an adopted row from one an
    author typed. So after a withdrawal the journal entry and the response are
    the only two places the origin can still exist."""

    def test_the_journal_entry_carries_the_origin(
        self, client, db_session, owner
    ):
        row = _scar(db_session, owner, HEADING, adopted=True)
        db_session.execute(_migration_module()._MOVE)
        db_session.commit()
        memory_id = row.id

        r = client.post(
            f"/api/agents/{owner['agent_id']}/memories/{memory_id}/withdraw",
            json={"reason": "superseded"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )
        assert r.status_code == 200, r.text

        entry = client.get(f"/api/journal/{r.json()['journal_entry_id']}")
        assert entry.status_code == 200, entry.text
        body = entry.json()["body"]
        assert HEADING in body, (
            "the row and its adoption link are both gone now; if the heading "
            "is not in this journal entry it does not exist anywhere"
        )
        assert "superseded" in body

    def test_the_withdraw_response_carries_the_origin(
        self, client, db_session, owner
    ):
        row = _scar(db_session, owner, HEADING, adopted=True)
        db_session.execute(_migration_module()._MOVE)
        db_session.commit()

        r = client.post(
            f"/api/agents/{owner['agent_id']}/memories/{row.id}/withdraw",
            json={"reason": "superseded"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["adopted_from_heading"] == HEADING
        # The scope column is null for a moved row, so without the field above
        # this response would report a lesson that never had an origin.
        assert payload["context_key"] is None

    def test_the_adoption_link_really_is_gone_afterwards(
        self, client, db_session, owner
    ):
        """THE CONTROL for this whole class. If the link survived a removal,
        the two tests above would be guarding nothing - provenance could just
        be recomputed."""
        row = _scar(db_session, owner, HEADING, adopted=True)
        memory_id = row.id
        db_session.commit()
        assert db_session.execute(
            select(MemoryTransition).where(
                MemoryTransition.target_memory_id == memory_id
            )
        ).scalars().all()

        client.post(
            f"/api/agents/{owner['agent_id']}/memories/{memory_id}/withdraw",
            json={"reason": "superseded"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )

        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id) is None
        assert db_session.execute(
            select(MemoryTransition).where(
                MemoryTransition.target_memory_id == memory_id
            )
        ).scalars().all() == []

    def test_a_row_with_no_origin_adds_no_line_to_the_journal(
        self, client, db_session, owner
    ):
        """Most rows were never adopted. They must not acquire a provenance
        sentence saying so - an absent origin is said by saying nothing."""
        row = _scar(db_session, owner, HEADING, adopted=False)
        db_session.commit()

        r = client.post(
            f"/api/agents/{owner['agent_id']}/memories/{row.id}/withdraw",
            json={"reason": "superseded"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )
        assert r.status_code == 200, r.text
        assert r.json()["adopted_from_heading"] is None

        entry = client.get(f"/api/journal/{r.json()['journal_entry_id']}")
        assert "Adopted from memory.md heading" not in entry.json()["body"]


class TestProvenanceIsNotAScope:
    def test_the_scan_does_not_read_the_new_column(self):
        """Provenance must never become the scan's input. The whole defect was
        a document location being resolved as a scope; moving it to a column
        the scan also reads would reproduce it under a better name."""
        source = (
            pathlib.Path(memory_scan.__file__).read_text()
        )
        assert "adopted_from_heading" not in source

    def test_a_moved_row_scans_as_still_active_not_unresolvable(
        self, db_session, owner
    ):
        """Behaviourally this is the only change, and it is a no-op: both
        verdicts take no action. That is the arithmetic DWB-705 refused the
        plain null on, and it holds for the move too."""
        row = _scar(db_session, owner, HEADING, adopted=True)
        assert memory_scan.scan_context(db_session, row) is (
            memory_scan.ContextLiveness.unresolvable
        )

        db_session.execute(_migration_module()._MOVE)
        db_session.expire_all()

        moved = db_session.get(AgentMemory, row.id)
        assert memory_scan.scan_context(db_session, moved) is (
            memory_scan.ContextLiveness.still_active
        )
