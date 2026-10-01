# Path: tests/test_memory_promote_dwb606.py
# File: test_memory_promote_dwb606.py
# Created: 2026-09-30 (DWB-606)
# Purpose: Guard scar-to-core promotion - both of Miles's triggers promote,
#          neither trigger alone from the WRONG signal promotes, an existing
#          row is retiered in place rather than duplicated, and tier=core has
#          exactly one write path in the app.
# Caller: pytest
# Callees: app.services.memory_promote, app.services.memory_scan
# Data In: factory agents/projects/epics/tickets, agent_memories rows
# Data Out: Assertions on tier, on which reason fired, and on write sites
# Last Modified: 2026-09-30 (DWB-611: scar_context_bound collapsed into scar;
#                the no-context-key case now asserts still_active, not
#                cannot_die, matching memory_scan.py's own inline ruling)

"""DWB-606 acceptance.

Two positive cases, reproduced against the ticket's own wording: "a scar with
fired_count=3 is promoted to tier=core... A scar whose context scan reports
'cannot die' is likewise promoted." Both proven against the STORED tier, not
against the return value alone - same discipline DWB-603's tests use for
fired_count and for the same reason: the ticket exists because a claim about a
write needs the write checked, not the function's opinion of itself.

The negative cases matter as much as the positive ones here, because this
promotion sits next to two OTHER movements that must not be confused with it:
`finished` (DWB-607's trigger, not this one) and `still_active` (nobody's
trigger). A test suite that only proves the two positive cases would pass a
build that promotes on ANY scan result, which is the "guard that passes
because the dangerous case answers the same way as the safe one" shape this
project keeps finding - here the dangerous case would be `finished` read as
"good enough" for CORE, which is a wrong promotion that never comes back
(section 7 hard rule 5's whole reason for treating CORE as difficult to enter).
"""

import ast
import pathlib

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import journal as journal_svc
from app.services import memory_promote as svc
from app.services import memory_scan

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


def _memory(db, *, agent_id, tier=MemoryTier.scar, fired_count=0, context_key=None):
    row = AgentMemory(
        agent_id=agent_id, tier=tier, body="a lesson",
        fired_count=fired_count, context_key=context_key,
    )
    db.add(row)
    db.flush()
    return row


def _stored_tier(db, memory_id):
    db.expire_all()
    return db.get(AgentMemory, memory_id).tier


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


class TestFiredThreeTimesPromotes:
    """ACCEPTANCE, half one: fired_count=3 promotes to core."""

    def test_fired_count_at_threshold_promotes(self, db_session, agent):
        scar = _memory(db_session, agent_id=agent["id"], fired_count=3)

        reason = svc.maybe_promote_scar(db_session, scar)

        assert reason == svc.ScarPromotionReason.fired_three_times
        assert _stored_tier(db_session, scar.id) == MemoryTier.core

    def test_fired_count_below_threshold_does_not_promote_on_its_own(
        self, db_session, agent, make_epic
    ):
        """Isolates fired_count from the OTHER trigger: a plain scar has no
        context_key and would trivially scan as cannot_die (see
        TestContextCannotDiePromotes), which would promote it regardless of
        fired_count and defeat the point of this test. Pinning the scar to a
        real, still-open epic holds the context signal at still_active so
        fired_count is the only variable in play.
        """
        make_epic(project_id=agent["project_id"], name="Live Epic", status="open")
        scar = _memory(
            db_session, agent_id=agent["id"],
            context_key="Live Epic / notes", fired_count=2,
        )

        reason = svc.maybe_promote_scar(db_session, scar)

        assert reason is None
        assert _stored_tier(db_session, scar.id) == MemoryTier.scar

    def test_fired_count_past_threshold_still_promotes(self, db_session, agent):
        """>= 3, not == 3: a scar that fires a fourth time before anything
        acted on the third must not be skipped past."""
        scar = _memory(db_session, agent_id=agent["id"], fired_count=5)
        assert svc.maybe_promote_scar(db_session, scar) == svc.ScarPromotionReason.fired_three_times


class TestContextCannotDiePromotes:
    """ACCEPTANCE, half two: a scan of `cannot_die` promotes to core, and
    Miles's own worked example (a general coding-standards lesson) is
    reproduced literally."""

    def test_a_context_that_resolves_to_nothing_promotes(self, db_session, agent):
        scar = _memory(
            db_session, agent_id=agent["id"],
            context_key="general coding-standards lesson",
        )

        reason = svc.maybe_promote_scar(db_session, scar)

        assert reason == svc.ScarPromotionReason.context_cannot_die
        assert _stored_tier(db_session, scar.id) == MemoryTier.core

    def test_a_scar_with_no_context_key_does_not_promote(self, db_session, agent):
        """DWB-611 changed this: post-collapse, all scars are context bound
        (Miles's ruling), so a missing context_key is a DATA GAP ("could not
        look"), not a deliberate general lesson - memory_scan.py now reports
        `still_active` for it, not `cannot_die`. Before the collapse this same
        memory would have promoted; the fact that it no longer does is the
        whole point of the DWB-604/611 sequencing fix, so this test exists to
        pin that behavior down rather than let it silently drift back."""
        scar = _memory(db_session, agent_id=agent["id"], context_key=None)
        assert svc.maybe_promote_scar(db_session, scar) is None
        assert _stored_tier(db_session, scar.id) == MemoryTier.scar


class TestWrongSignalsDoNotPromote:
    """THE NEGATIVE HALF. `finished` is DWB-607's trigger, not this one, and
    `still_active` is nobody's. A build that promotes on either would pass
    the two classes above and still be wrong."""

    def test_a_finished_context_does_not_promote_to_core(
        self, db_session, agent, make_epic
    ):
        """A closed epic means the context is DONE, which routes to the
        JOURNAL (DWB-607), not to CORE. Promoting it here would be the wrong
        movement succeeding for the wrong reason."""
        make_epic(project_id=agent["project_id"], name="Wrapped Epic", status="completed")
        scar = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.scar,
            context_key="Wrapped Epic / notes", fired_count=0,
        )

        assert memory_scan.scan_context(db_session, scar) == memory_scan.ContextLiveness.finished
        assert svc.maybe_promote_scar(db_session, scar) is None
        assert _stored_tier(db_session, scar.id) == MemoryTier.scar

    def test_a_still_open_context_with_low_fired_count_does_not_promote(
        self, db_session, agent, make_epic
    ):
        make_epic(project_id=agent["project_id"], name="Live Epic", status="open")
        scar = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.scar,
            context_key="Live Epic / notes", fired_count=1,
        )
        assert svc.maybe_promote_scar(db_session, scar) is None
        assert _stored_tier(db_session, scar.id) == MemoryTier.scar


class TestRetieringInPlace:
    """"Broaden to CORE, remove from scars" (Miles) - the SAME row, not a
    copy, and CORE is context-free so context_key must not survive."""

    def test_promoted_row_keeps_its_id_and_fired_count_history(
        self, db_session, agent
    ):
        scar = _memory(db_session, agent_id=agent["id"], fired_count=3)
        original_id = scar.id

        svc.maybe_promote_scar(db_session, scar)
        db_session.expire_all()
        row = db_session.get(AgentMemory, original_id)

        assert row is not None
        assert row.fired_count == 3, "promotion must not erase the history that triggered it"

    def test_context_key_is_cleared_on_promotion(self, db_session, agent):
        scar = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.scar,
            context_key="general coding-standards lesson",
        )
        svc.maybe_promote_scar(db_session, scar)
        db_session.expire_all()
        assert db_session.get(AgentMemory, scar.id).context_key is None


class TestPromoteToCoreDirectly:
    """The shared helper's own contract, independent of the scar movement -
    DWB-608 will call this directly with no existing AgentMemory row."""

    def test_with_no_existing_memory_it_creates_a_new_row(self, db_session, agent):
        created = svc.promote_to_core(
            db_session, agent_id=agent["id"], body="promoted from a journal entry",
            source_journal_id=None,
        )
        assert created.id is not None
        assert created.tier == MemoryTier.core
        assert created.body == "promoted from a journal entry"

    def test_source_journal_id_is_recorded_when_given(self, db_session, agent):
        # source_journal_id is a real FK (agent_memories -> journal_entries),
        # so the referenced row has to exist first.
        entry = journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="the episode this came from",
        )
        created = svc.promote_to_core(
            db_session, agent_id=agent["id"], body="from the journal",
            source_journal_id=entry.id,
        )
        assert created.source_journal_id == entry.id


class TestScopeGuard:
    @pytest.mark.parametrize(
        "tier", [MemoryTier.working, MemoryTier.core, MemoryTier.raw]
    )
    def test_non_scar_tiers_are_refused(self, db_session, agent, tier):
        memory = _memory(db_session, agent_id=agent["id"], tier=tier)
        with pytest.raises(memory_scan.ScanError) as exc_info:
            svc.maybe_promote_scar(db_session, memory)
        assert exc_info.value.code == "not_a_scar"


# ---------------------------------------------------------------------------
# Structural half: tier=core has exactly one WRITE PATH (one file), not one
# line - this write path legitimately branches into two expressions (retier
# vs construct) inside a single function, which is the ticket's own
# requirement ("a single shared core-write helper"), so the guard is scoped
# to the file rather than to a single occurrence the way journal.py's
# retrieval_count guard is.
# ---------------------------------------------------------------------------


def _python_sources() -> list[pathlib.Path]:
    return sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _is_memory_tier_core(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "core"
        and isinstance(node.value, ast.Name)
        and node.value.id == "MemoryTier"
    )


def _tier_core_write_files() -> set[str]:
    """Every FILE in app/ that writes MemoryTier.core onto a `tier` field -
    as an attribute assignment (`x.tier = MemoryTier.core`) or as a
    constructor/`.values()` keyword (`tier=MemoryTier.core`).

    Comparisons (`if memory.tier == MemoryTier.core`) are common and correct
    all over the scoring code and must NOT count as writes; only Assign and
    Call-keyword shapes are write shapes.
    """
    files: set[str] = set()
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(APP_DIR.parent))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (
                        isinstance(t, ast.Attribute)
                        and t.attr == "tier"
                        and _is_memory_tier_core(node.value)
                    ):
                        files.add(rel)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "tier" and _is_memory_tier_core(kw.value):
                        files.add(rel)
    return files


class TestExactlyOneCoreWritePath:
    def test_the_scan_can_see_the_identifier_at_all(self):
        sources = _python_sources()
        assert len(sources) > 20, f"only scanned {len(sources)} files"
        mentions = [p for p in sources if "MemoryTier.core" in p.read_text(encoding="utf-8")]
        assert len(mentions) >= 2, (
            f"expected the model and the promotion module to mention "
            f"MemoryTier.core; found {[str(m) for m in mentions]}"
        )

    def test_exactly_one_file_writes_tier_core(self):
        files = _tier_core_write_files()
        assert files == {"app/services/memory_promote.py"}, (
            "MemoryTier.core must be written through exactly one file (DWB-606: "
            f"'the two should not duplicate the write path'). Found: {files}"
        )
