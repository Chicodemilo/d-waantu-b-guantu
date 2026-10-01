# Path: tests/test_memory_withdrawal_dwb626.py
# File: test_memory_withdrawal_dwb626.py
# Created: 2026-10-01 (DWB-626)
# Purpose: Withdrawal, and the FK defect it fixes. Proves a bare delete cannot
#          remove an adopted row, that journal_and_remove can, that the journal
#          lands first, that nothing is left pointing at a removed row, and that
#          only the owner may withdraw.
# Caller: pytest
# Callees: app.services.memory_removal, app.services.memory_withdraw,
#          POST /api/agents/{id}/memories/{mid}/withdraw,
#          GET /api/memory-transitions/{id}
# Data In: tmp_path repo, factory project + agent, a memory with a transition
#          pointing at it (the adopted shape)
# Data Out: assertions on removal, ordering, FK state and ownership
# Last Modified: 2026-10-01 (DWB-626)

"""Nothing could leave agent_memories, and the rows worth removing were the
rows that could not be.

Before this the whole memory surface was GET memory, GET scored, POST append,
POST compact, POST condense, POST scaffold-memory, POST memories. No PATCH, no
DELETE, nothing that edits or retracts.

Underneath that, a defect that makes the gap worse than it looks.
`memory_transitions.target_memory_id` references `agent_memories` with delete
rule NO ACTION, and adoption points a transition at every row it creates, so a
bare `db.delete` on an adopted row raises 1451. The DELETABLE set is exactly the
RAW set - checked in both directions rather than by subtraction - so the only
rows removable today are the ones nothing can reach, and every row worth
withdrawing is behind the constraint.

Latent rather than live: neither eviction path has ever had a candidate. But
every row shares one clock origin and that session is still open, so WORKING
decays in lockstep and the candidates reach the floor together - the first sweep
after it closes hits the FK on every one at once, inside a try/except that rolls
back and logs, where 1451 reads identically to "nothing to evict".
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.services import memory_removal, memory_withdraw


@pytest.fixture
def adopted(db_session, client, tmp_path):
    """A memory in the ADOPTED shape: a transition row points at it.

    This is the shape that matters. A memory with nothing pointing at it is the
    raw-path shape, which deletes cleanly and therefore cannot demonstrate
    anything about the constraint.
    """
    project = client.post("/api/projects", json={
        "prefix": "WDR", "name": "Withdraw", "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": "Withdrawer",
        "role": "backend-worker", "api_key": "dwb626-wdr",
    }).json()

    memory = AgentMemory(
        agent_id=agent["id"], tier=MemoryTier.scar,
        body="recover with git checkout of that one path",
        context_key="Working rules",
    )
    db_session.add(memory)
    db_session.flush()

    run = MemoryTransitionRun(
        project_id=project["id"], direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
    )
    db_session.add(run)
    db_session.flush()
    transition = MemoryTransition(
        project_id=project["id"], agent_id=agent["id"], run_id=run.id,
        state=TransitionState.written, source_excerpt="- a lesson\n",
        decided_tier=MemoryTier.scar, decided_by="Withdrawer",
        target_memory_id=memory.id,
    )
    db_session.add(transition)
    db_session.flush()
    return project, agent, memory, transition


class TestTheConstraintIsReal:
    """Acceptance 3 and 4: demonstrate the absence rather than assert it."""

    def test_a_bare_delete_cannot_remove_an_adopted_row(self, db_session, adopted):
        """The defect, reproduced. This is what every removal path does today.

        Ends the test: the session is unusable after an IntegrityError, which is
        itself part of the finding - inside `consolidate_agent` this poisons the
        transaction and the journal entry written moments earlier rolls back
        with it, leaving no trace that anything was attempted.
        """
        _project, _agent, memory, _t = adopted
        db_session.delete(memory)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_the_raw_shape_deletes_cleanly_so_the_refusal_is_the_fk(
        self, db_session, adopted
    ):
        """The positive control, without which the refusal above means nothing.

        A delete that failed for any other reason - a broken fixture, a missing
        row - would look identical. This row differs in exactly one way: nothing
        points at it.
        """
        _project, agent, _memory, _t = adopted
        unpointed = AgentMemory(
            agent_id=agent["id"], tier=MemoryTier.raw, body="nothing points here"
        )
        db_session.add(unpointed)
        db_session.flush()
        db_session.delete(unpointed)
        db_session.flush()  # no raise
        assert db_session.get(AgentMemory, unpointed.id) is None


class TestJournalAndRemove:
    def test_it_removes_an_adopted_row(self, db_session, adopted):
        """Acceptance 4. The same row the bare delete could not touch."""
        _project, _agent, memory, _t = adopted
        memory_id = memory.id

        memory_removal.journal_and_remove(
            db_session, memory, tags=["withdrawn"], reason="superseded"
        )
        db_session.flush()
        assert db_session.get(AgentMemory, memory_id) is None

    def test_nothing_is_left_pointing_at_the_removed_row(self, db_session, adopted):
        """Acceptance 6. A withdrawal that left a dangling reference would be
        worse than no withdrawal."""
        _project, _agent, memory, transition = adopted
        memory_id = memory.id

        memory_removal.journal_and_remove(db_session, memory, tags=["withdrawn"])
        db_session.flush()
        db_session.refresh(transition)
        assert transition.target_memory_id is None
        # The DECISION record survives; only the pointer to a row that no longer
        # exists is cleared. A withdrawal must not erase that a call was made.
        assert transition.decided_tier == MemoryTier.scar
        assert transition.decided_by == "Withdrawer"

    def test_the_body_reaches_the_journal_with_its_original_date(
        self, db_session, adopted
    ):
        _project, agent, memory, _t = adopted
        original_body, original_created = memory.body, memory.created_at

        entry = memory_removal.journal_and_remove(
            db_session, memory, tags=["withdrawn"], reason="it was wrong"
        )
        db_session.flush()

        stored = db_session.get(JournalEntry, entry.id)
        assert stored is not None
        assert original_body in stored.body
        assert "it was wrong" in stored.body
        # DWB-605: the lesson existed from its own created_at. Dating the entry
        # today would make the journal claim it was learned when it was retracted.
        assert stored.created_at == original_created
        assert stored.agent_id == agent["id"]

    def test_the_three_steps_happen_in_that_order(self):
        """The order asserted over the SYNTAX TREE, not over the source text.

        The first version of this test compared `str.index` positions and went
        red against correct code, because the docstring and the comments name
        `target_memory_id` long before the statement that writes it. A
        source-string tripwire breaks the moment your own prose quotes the code
        it is checking - which is exactly why the rule is to walk the AST, where
        a comment cannot be mistaken for a statement.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(memory_removal.journal_and_remove))
        )
        journal_at = fk_at = delete_at = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name == "create_entry" and journal_at is None:
                    journal_at = node.lineno
                if name == "delete" and delete_at is None:
                    delete_at = node.lineno
                for kw in node.keywords:
                    if kw.arg == "target_memory_id" and fk_at is None:
                        fk_at = node.lineno
        assert journal_at and fk_at and delete_at, (journal_at, fk_at, delete_at)
        assert journal_at < fk_at < delete_at, (
            f"journal (line {journal_at}), then break the FK (line {fk_at}), "
            f"then delete (line {delete_at}) - in that order"
        )


class TestTheJournalLandsFirst:
    """Acceptance 5, as a SEQUENCE rather than an end state.

    Both orders produce the same end state on the happy path, so asserting the
    end state cannot tell them apart. Only a failure injected BETWEEN the two
    halves can, which is what this does.
    """

    def test_a_failure_during_the_delete_leaves_the_memory_and_the_journal(
        self, db_session, adopted, monkeypatch
    ):
        _project, agent, memory, _t = adopted
        memory_id = memory.id

        def boom(_obj):
            raise RuntimeError("storage died between the journal and the delete")

        monkeypatch.setattr(db_session, "delete", boom)
        with pytest.raises(RuntimeError):
            memory_removal.journal_and_remove(db_session, memory, tags=["withdrawn"])

        # The memory survived, and the journal is merely early. The reverse -
        # a deleted row whose content never reached the journal - is the one
        # unrecoverable outcome in the design (hard rule 4).
        assert db_session.get(AgentMemory, memory_id) is not None
        entries = db_session.query(JournalEntry).filter_by(agent_id=agent["id"]).all()
        assert len(entries) == 1, "the journal entry must already have landed"


class TestOwnership:
    """Acceptance 7, and the ruling: the owning agent, nobody else."""

    def test_another_agent_cannot_withdraw_it(self, db_session, client, adopted):
        project, agent, memory, _t = adopted
        intruder = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Intruder",
            "role": "backend-worker", "api_key": "dwb626-int",
        }).json()

        with pytest.raises(memory_withdraw.WithdrawError) as e:
            memory_withdraw.withdraw_memory(
                db_session, agent_id=agent["id"], memory_id=memory.id,
                acting_agent_id=intruder["id"],
            )
        assert e.value.code == "not_owner"
        assert db_session.get(AgentMemory, memory.id) is not None

    def test_an_unattributed_withdrawal_is_refused(self, db_session, adopted):
        _project, agent, memory, _t = adopted
        with pytest.raises(memory_withdraw.WithdrawError) as e:
            memory_withdraw.withdraw_memory(
                db_session, agent_id=agent["id"], memory_id=memory.id,
                acting_agent_id=None,
            )
        assert e.value.code == "actor_required"

    def test_the_owner_can(self, db_session, adopted):
        _project, agent, memory, _t = adopted
        memory_id = memory.id
        result = memory_withdraw.withdraw_memory(
            db_session, agent_id=agent["id"], memory_id=memory_id,
            acting_agent_id=agent["id"], reason="superseded by a later lesson",
        )
        db_session.flush()
        assert result["withdrawn"] is True
        assert result["journal_entry_id"] is not None
        assert db_session.get(AgentMemory, memory_id) is None
