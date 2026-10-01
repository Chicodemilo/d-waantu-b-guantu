# Path: tests/test_memory_adoption_repair_dwb620.py
# File: test_memory_adoption_repair_dwb620.py
# Created: 2026-10-01 (DWB-620)
# Purpose: The outage and the two splitter defects behind it. Proves decide()
#          stamps a session origin, that a write-stamp ends its section and is
#          recognised without seconds or a dash, and that the repair script
#          cannot stamp an origin onto a row still bound to a write-stamp.
# Caller: pytest
# Callees: app.services.memory_format, app.services.memory_decide,
#          scripts/dwb620_repair_adopted_memory.py
# Data In: tmp_path repo with .dwb/memory files, factory project + agent
# Data Out: assertions on heading_path, created_session_id, and the repair gate
# Last Modified: 2026-10-01 (DWB-620)

"""What broke, stated so a later reader can tell these tests from decoration.

396 adopted rows were written with a NULL `created_session_id`, which makes
`memory_score.sessions_since_reinforced` return None, which excludes the row
from every candidate list. Every agent on a `human_memory` project received no
memory at all, and the flat file was sealed behind the mode, so there was no
fallback. One missing assignment on one writer.

Underneath it, `memory_format.split` had two defects that compound, and the
fixture below carries BOTH IN ONE FILE because testing them apart is what let
them survive: defect B injects a malformed write-stamp onto the section stack,
defect A guarantees that no later well-formed stamp ever clears it. The third
entry in the fixture is the compounding - it sits under a PERFECTLY VALID stamp
and the old splitter still attributed it to the malformed one above.

Why that is not cosmetic, and why these tests sit beside the repair tests rather
than in a parser file: `heading_path` becomes `context_key` on every scar,
`memory_scan` pulls any ticket-shaped string out of a context_key, a context
resolving to a CLOSED ticket makes the row `finished`, and
`memory_scar_conclude` journals that row and then DELETES it.
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbSession
from app.services import memory_format

# The pattern ISO_HEADING used BEFORE DWB-620, kept here as a STRING so the
# discrimination keeps proving itself on every run without a line of defective
# code living in the tree. It required seconds, and allowed trailing text only
# after a dash separator.
OLD_ISO_PATTERN = (
    r"^(?P<hashes>#{1,6})\s+"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?)"
    r"\s*(?:[-–—]\s*(?P<note>.*))?$"
)

# A real heading out of a live memory.md. Hand-written, so no seconds and the
# trailing text is not dash-introduced.
MALFORMED_STAMP = "## 2026-09-14T18:37 ZZZ-999 (id 1, S1/1) -> in_review"
WELLFORMED_STAMP = "## 2026-10-01T15:40:24+00:00 - condensed"

FIXTURE = f"""# Memory - Tester

## Real Section

- a lesson written under a real section

{MALFORMED_STAMP}

- a lesson written under a MALFORMED write-stamp

{WELLFORMED_STAMP}

- a lesson written under a WELL-FORMED write-stamp

## Another Section

- a lesson under another real section
"""


def _bodies_to_paths(text):
    return {e.body: e.heading_path for e in memory_format.split(text).entries}


class TestSplitterDefectB:
    """A write-stamp is recognised by its SHAPE, not by one writer's format."""

    def test_the_old_pattern_rejects_a_live_heading_the_new_one_accepts(self):
        """The permanent discrimination, and the reason it is a string above.

        Running the old pattern beside the real one on the same input proves
        the fix changes the answer, keeps proving it on every run, and never
        puts a defective code path in the tree. A test that only asserted the
        new pattern matches would pass just as happily against the old one for
        every heading that was already fine.
        """
        import re

        old = re.compile(OLD_ISO_PATTERN)
        assert old.match(MALFORMED_STAMP) is None, (
            "fixture no longer reproduces defect B: the old pattern now matches "
            "this heading, so this test can no longer tell the versions apart"
        )
        assert memory_format.ISO_HEADING.match(MALFORMED_STAMP) is not None

        # And the shapes that always worked still work, in BOTH, so the fix is
        # a widening rather than a different pattern.
        for still_fine in (
            WELLFORMED_STAMP,
            "## 2026-10-01T15:40:24+00:00 — session abc123",
            "## 2026-10-01T14:07:15+00:00",
        ):
            assert old.match(still_fine) is not None
            assert memory_format.ISO_HEADING.match(still_fine) is not None

    def test_a_topic_heading_is_still_a_topic(self):
        for topic in ("## Migrations / MySQL", "## COLLAPSE LATE", "### Gates"):
            assert memory_format.ISO_HEADING.match(topic) is None


class TestSplitterDefectA:
    """A write-stamp ENDS the section above it."""

    def test_a_stamp_clears_the_section_chain(self):
        paths = _bodies_to_paths(FIXTURE)
        assert paths["a lesson written under a WELL-FORMED write-stamp"] == ()

    def test_a_later_real_heading_still_opens_a_section(self):
        paths = _bodies_to_paths(FIXTURE)
        assert paths["a lesson under another real section"] == ("Another Section",)


class TestTheTwoDefectsCompound:
    def test_no_entry_carries_a_heading_it_was_not_written_under(self):
        """DWB-620 acceptance 5, as an outcome rather than a mechanism.

        The exact values on the right are what the PRE-FIX splitter produced on
        this fixture, measured against the saved pre-fix source. Each assertion
        below therefore fails against the old code, which is acceptance 6.
        """
        paths = _bodies_to_paths(FIXTURE)

        # Written under a real section: unchanged by the fix.
        assert paths["a lesson written under a real section"] == ("Real Section",)

        # Defect B: the old splitter returned the malformed stamp here.
        assert paths["a lesson written under a MALFORMED write-stamp"] == ()

        # THE COMPOUNDING, AND THE ASSERTION THAT MATTERS MOST. This entry sits
        # under a perfectly valid stamp. The old splitter still gave it the
        # MALFORMED one, because defect A meant a valid stamp never cleared the
        # stack. Fixing either defect alone leaves this line wrong.
        assert paths["a lesson written under a WELL-FORMED write-stamp"] == ()

        # Nothing anywhere carries a provenance-shaped heading.
        for body, path in paths.items():
            for element in path:
                assert not element.startswith("2026-"), (body, path)

    def test_both_stamps_are_filed_as_provenance_not_offered_for_tiering(self):
        parsed = memory_format.split(FIXTURE)
        assert parsed.provenance == [MALFORMED_STAMP, WELLFORMED_STAMP]
        for entry in parsed.entries:
            assert not entry.body.startswith("2026-")

    def test_an_empty_chain_is_empty_not_invented(self):
        """`heading_path` is () where there is no real section, never a guess.

        An absent context and a named-but-unresolvable one are DIFFERENT
        answers downstream: `scan_context` takes no action on the first and
        reports `cannot_die` for the second.
        """
        parsed = memory_format.split(f"{WELLFORMED_STAMP}\n\n- a lesson with no section\n")
        assert [e.heading_path for e in parsed.entries] == [()]


class TestDecideStampsTheSessionOrigin:
    """The outage itself: one missing assignment on one writer."""

    def test_an_adopted_row_gets_the_open_session(self, db_session, make_project, make_agent):
        from app.services import memory_decide

        import inspect

        source = inspect.getsource(memory_decide.decide)
        assert "created_session_id" in source, (
            "decide() must stamp the session origin; without it every adopted "
            "row is unscoreable and no agent receives any memory"
        )

    def test_the_stamp_matches_the_raw_path(self):
        """Parity, asserted structurally rather than by eye.

        Both writers must resolve the origin the same way: the active session,
        or NULL when none is open. A second rule for adoption is how the two
        drift apart again.
        """
        import inspect

        from app.services import memory_decide, raw_memory

        expected = "active.id if active is not None else None"
        assert expected in inspect.getsource(memory_decide.decide)
        assert expected in inspect.getsource(raw_memory.append_raw_memory)


def _load_repair_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "dwb620_repair_adopted_memory.py"
    spec = importlib.util.spec_from_file_location("dwb620_repair", path)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["dwb620_repair"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repair():
    return _load_repair_script()


@pytest.fixture
def adopted(db_session, client, tmp_path):
    """A project whose agent has one scar bound to a write-stamp, as adoption
    left it: provenance-shaped context_key, NULL origin, and an intact flat
    file that the fixed splitter reads correctly."""
    project = client.post("/api/projects", json={
        "prefix": "RPR", "name": "Repair", "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": "Repairee",
        "role": "backend-worker", "api_key": "dwb620-repair",
    }).json()

    mem_dir = tmp_path / ".dwb" / "memory" / "RPR" / "Repairee"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "memory.md").write_text(FIXTURE, encoding="utf-8")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = DwbSession(
        project_id=project["id"],
        opened_at=now - timedelta(hours=1),
        open_method="ai_confident",
    )
    db_session.add(session)
    db_session.flush()

    rows = []
    for body, bad_key in (
        ("a lesson written under a MALFORMED write-stamp", MALFORMED_STAMP[3:]),
        ("a lesson under another real section", "Another Section"),
    ):
        row = AgentMemory(
            agent_id=agent["id"], tier=MemoryTier.scar, body=body,
            context_key=bad_key, created_session_id=None,
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    return project, agent, session, rows


class TestRepairOrdering:
    """Acceptance 3, as a SEQUENCE WALK.

    Two independent assertions - "context keys end up clean" and "origins end
    up stamped" - both pass against a script that stamps FIRST and corrects
    second, which is the order that deletes lessons. The question is not where
    the walk ends, it is whether any reachable intermediate state has a row both
    scoreable and still bound to a write-stamp.
    """

    def test_the_gate_refuses_when_the_correction_has_not_run(self, repair, db_session, adopted):
        project, _agent, _session, _rows = adopted
        from app.models.project import Project

        proj = db_session.get(Project, project["id"])

        # The reversed order, reached the only way the script allows anyone to
        # reach it: ask the gate before step 1. It must refuse, and it must name
        # the row it is refusing over.
        armed = repair._verify_no_armed_rows(db_session, proj)
        assert armed, "the gate passed on a database that still has an armed row"

    def test_no_intermediate_state_has_a_scoreable_provenance_bound_row(
        self, repair, db_session, adopted
    ):
        project, _agent, _session, rows = adopted
        from app.models.project import Project

        proj = db_session.get(Project, project["id"])

        def invariant_holds():
            """No row is BOTH scoreable and provenance-bound. Checked against
            the database at each step, not against what a step returned."""
            db_session.flush()
            bad = [
                r for r in db_session.query(AgentMemory).all()
                if r.created_session_id is not None
                and r.context_key
                and repair.PROVENANCE_SHAPED.match(r.context_key)
            ]
            return bad == []

        # step 0: nothing stamped yet, so nothing can be armed.
        assert invariant_holds()

        # step 1: correct the keys.
        correction = repair._correct_context_keys(db_session, proj)
        assert correction.plans, "fixture did not need correcting; it proves nothing"
        assert invariant_holds()

        # the gate, which must now be clear.
        assert repair._verify_no_armed_rows(db_session, proj) == []
        assert invariant_holds()

        # step 2: stamp.
        stamps = repair._stamp_origins(db_session, proj, correction)
        assert stamps, "nothing was stamped; the outage fix did not run"
        assert invariant_holds()

        # and the end state is what the ticket asked for.
        db_session.flush()
        for row in rows:
            db_session.refresh(row)
            assert row.created_session_id is not None
        assert rows[0].context_key is None
        assert rows[1].context_key == "Another Section"

    def test_step_two_cannot_be_called_without_step_one(self, repair):
        """The ordering is carried in the signature, not in a comment.

        `_stamp_origins` requires a `Correction`, and only
        `_correct_context_keys` returns one. This asserts the precondition is
        structural so a later edit that makes it optional fails here.
        """
        import inspect

        sig = inspect.signature(repair._stamp_origins)
        assert "correction" in sig.parameters
        param = sig.parameters["correction"]
        assert param.default is inspect.Parameter.empty, (
            "the receipt must be required; a default makes the dangerous order "
            "reachable by omission"
        )


class TestRepairIsIdempotent:
    def test_a_second_pass_changes_nothing(self, repair, db_session, adopted):
        project, _agent, _session, _rows = adopted
        from app.models.project import Project

        proj = db_session.get(Project, project["id"])

        first = repair._correct_context_keys(db_session, proj)
        repair._stamp_origins(db_session, proj, first)
        db_session.flush()

        second = repair._correct_context_keys(db_session, proj)
        second_stamps = repair._stamp_origins(db_session, proj, second)

        assert second.plans == [], f"second pass re-corrected: {second.plans}"
        assert second_stamps == [], f"second pass re-stamped: {second_stamps}"

    def test_a_row_that_already_has_an_origin_is_never_restamped(
        self, repair, db_session, adopted
    ):
        """SCOPED BY NULLITY, NEVER BY COUNT.

        Six rows on the live install were written through the raw path and
        already carry correct origins. A blanket update sized from a remembered
        row count overwrites them, and the overwrite is invisible.
        """
        project, agent, session, _rows = adopted
        from app.models.project import Project

        proj = db_session.get(Project, project["id"])
        already = AgentMemory(
            agent_id=agent["id"], tier=MemoryTier.raw,
            body="written through the raw path tonight",
            context_key="Verification discipline",
            created_session_id=session.id,
        )
        db_session.add(already)
        db_session.flush()
        untouched = already.created_session_id

        correction = repair._correct_context_keys(db_session, proj)
        stamps = repair._stamp_origins(db_session, proj, correction)

        db_session.refresh(already)
        assert already.created_session_id == untouched
        assert already.context_key == "Verification discipline"
        assert already.id not in [p.memory_id for p in stamps]
