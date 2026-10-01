# Path: app/services/memory_adopt.py
# File: memory_adopt.py
# Created: 2026-09-30 (DWB-594)
# Purpose: The SNAPSHOT phase of an adoption - split every agent's memory.md
#          into candidate entries and write one pending memory_transitions row
#          per candidate. No judgment, no tiering, no mode change.
# Caller: app/services/project.py (the BEGIN edge of stock -> adopting)
# Callees: app/services/memory_format (the shared splitter), app/models
# Data In: db Session, Project, MemoryTransitionRun
# Data Out: Enumeration (counts + the rows created)
# Last Modified: 2026-09-30 (DWB-594)

"""Snapshot: turn flat memory files into candidate rows. Phase 1 of five.

DWB-594 phase 1, verbatim: "Deterministic, no judgment, one `pending` row per
candidate. A script that needs to decide what counts as an entry has already
failed this phase."

A SNAPSHOT THAT MAKES A JUDGMENT HAS FAILED THE PHASE. That is the whole test
for whether code belongs in this module: if it decides anything, it is in the
wrong file. Tiering here would rubber-stamp in-the-moment salience, which is
precisely the judgment consolidation exists to make later.

So there is no tiering here and no proposed_tier. This module answers exactly
one question - what are the candidates - and it answers it by delegating to
`memory_format.split`, which is the shared understanding of the file format that
the revert renderer also imports. A second private parser here is the drift
criterion 6 forbids.

THE SOURCE EXCERPT IS A RENDERED ENTRY, NOT A RAW SLICE. Each candidate carries
the heading chain it was filed under - `## Verification discipline` and the
like - and `memory_transitions` has no column for that. Rather than add one,
`source_excerpt` holds `memory_format.render([entry])`: the entry rendered back
through the shared module, heading chain included. `split(source_excerpt)`
recovers the entry and its chain exactly, because that render-then-split
identity is the format module's round-trip test.

A `heading_path` column was the alternative and was rejected: it would be a
second representation of something the format module already encodes, and it
could drift from the excerpt sitting beside it.

ZERO CANDIDATES IS A LEGITIMATE OUTCOME, NOT AN ERROR. A project whose agents
all have empty memory files has nothing to adopt, and that must not be confused
with an enumeration that never ran.

A COUNT CANNOT TELL "ran and found nothing" FROM "never ran". `enumerated_at` on
the run is the disambiguator and the cutover guard refuses while it is NULL
(DWB-593). This module does NOT stamp it: DWB-593's BEGIN edge stamps it after
`enumerate_for_run` returns, so the ordering lives in one place rather than two.

AND ZERO IS A FACT ABOUT THE SPLITTER, NOT ABOUT THE FILES. That is the second
half, and it is the one that nearly shipped wrong. The measurement in
`memory_format` proves the risk is real rather than theoretical: a bullet-only
splitter returns ZERO for a 202-line file full of lessons, and zero looks
identical to a file with nothing in it. Cutting a project over on that reading
seals a store whose agents genuinely have memory - the amnesia bug arriving
through a different door.

So zero is CORROBORATED against the source before it is trusted, and the two
states never share a code path:

  * nothing to adopt        - every file absent, or empty, or structure-only.
                              Safe: `enumerate_for_run` returns 0 and the caller
                              cuts through.
  * found nothing in SOMETHING - a file with real content produced no
                              candidates, or could not be read at all. A defect.
                              `enumerate_for_run` RAISES, which rolls back the
                              run and the mode change together because it runs
                              inside the caller's transaction.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionState,
)
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.services import memory_format


@dataclass
class Enumeration:
    """What the snapshot found. Counts AND the reason they are what they are.

    `agents_with_no_memory` is carried separately from a bare zero because the
    two are different facts: a project with no agents at all and a project whose
    agents have all written nothing both enumerate to zero candidates, and only
    one of those is worth a second look before a cutover.
    """

    rows: list[MemoryTransition] = field(default_factory=list)
    agents_seen: int = 0
    agents_with_no_memory: int = 0
    # Files that exist but could not be read. Surfaced rather than swallowed: a
    # file skipped for an IO error looks exactly like a file with no lessons,
    # and adopting past it would lose that agent's memory at cutover.
    unreadable: list[str] = field(default_factory=list)
    # Files that HAVE content and yielded no candidates anyway. This is the
    # state the TL ruled must never share a code path with "nothing to adopt":
    # zero candidates is a fact about the SPLITTER, not about the files, and a
    # splitter that returns zero for a file full of lessons is the amnesia bug
    # arriving through a different door. Always a defect, never a cutover.
    content_without_candidates: list[str] = field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.rows)

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def is_defective(self) -> bool:
        """True when something was there and nothing came back.

        "Nothing to adopt" and "found nothing in something" are different facts
        and only the first is safe to cut over on. An unreadable file counts as
        defective for the same reason: it is content we could not see, not
        content that is not there.
        """
        return bool(self.content_without_candidates or self.unreadable)


def _memory_md_path(project: Project, agent: Agent) -> Path:
    """Canonical memory.md path. Mirrors agent._memory_dir and
    memory_trace._memory_md_path (DWB-401 relocated memory to .dwb/)."""
    base = (project.repo_path or ".").rstrip("/")
    return Path(base) / ".dwb" / "memory" / project.prefix / agent.name / "memory.md"


def _project_agents(db: Session, project_id: int) -> list[Agent]:
    """Active agents on the project, by the DB-authoritative bridge.

    Ordered by id so enumeration is deterministic across runs (DWB-594
    acceptance 1). An unordered query would produce the same SET of rows in a
    different order, which is a different answer to "identical candidate rows".
    """
    return list(
        db.execute(
            select(Agent)
            .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
            .where(ProjectAgent.project_id == project_id)
            .where(Agent.is_active.is_(True))
            .order_by(Agent.id.asc())
        )
        .scalars()
        .all()
    )


def enumerate_candidates(
    db: Session,
    project: Project,
    run: MemoryTransitionRun,
    *,
    persist: bool = True,
) -> Enumeration:
    """Split every agent's memory.md into pending transition rows.

    Deterministic: agents in id order, entries in source order, nothing sampled
    or timed. Running it twice on an unchanged tree produces identical rows,
    which is DWB-594 acceptance 1 and is structural here rather than tested into
    existence.

    `persist=False` is the DRY RUN (acceptance 5): the rows are built and
    returned but never added to the session, `run.enumerated_at` is NOT stamped,
    and the file is not touched. The caller gets the full plan - every candidate
    and what the store would look like - with no side effect. Stamping the run
    on a dry run would be the worst of both: nothing enumerated, but the cutover
    guard satisfied that something had been.

    IDEMPOTENCE IS THE CALLER'S PROBLEM, NOT THIS FUNCTION'S, and that is
    deliberate. Phase 4 (sweep) re-runs this to pick up anything appended since
    the snapshot, and it needs to know what is already enumerated in order to
    add only the difference. Making this function silently skip duplicates would
    hide that difference from the sweep, which is the one thing the sweep exists
    to see.
    """
    result = Enumeration()

    for agent in _project_agents(db, project.id):
        result.agents_seen += 1
        path = _memory_md_path(project, agent)

        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Never written. A normal state for a new agent, not a failure.
            result.agents_with_no_memory += 1
            continue
        except (OSError, UnicodeDecodeError):
            # Exists but unreadable. NOT counted as "no memory": adopting past
            # it would silently drop that agent's lessons at cutover, and the
            # two states must stay distinguishable.
            result.unreadable.append(str(path))
            continue

        parsed = memory_format.split(text)
        if not parsed.entries:
            # The corroboration. Checked against the RAW TEXT, never against the
            # splitter's own output: a check that reused the splitter would agree
            # with it by construction and could corroborate nothing.
            if _has_lesson_shaped_content(text):
                # Content went in, nothing came out. A defect, never a cutover.
                result.content_without_candidates.append(str(path))
            else:
                # Only headings and blank lines: a fresh condense marker and a
                # title. Genuinely nothing to adopt.
                result.agents_with_no_memory += 1
            continue

        for entry in parsed.entries:
            row = MemoryTransition(
                project_id=project.id,
                agent_id=agent.id,
                # `direction` lives on the RUN, stated once, not repeated on
                # every entry (DWB-593).
                run_id=run.id,
                state=TransitionState.pending,
                # The entry rendered back through the shared module, so the
                # heading chain travels with it and split() recovers both.
                source_excerpt=memory_format.render([entry]),
            )
            result.rows.append(row)
            if persist:
                db.add(row)

    if persist:
        db.flush()

    return result


_LESSON_SHAPES = ("- ", "* ", "+ ")


def _has_lesson_shaped_content(text: str) -> bool:
    """True when the file holds anything that is not provenance or structure.

    Used only to tell a legitimately lesson-free file (a fresh condense marker
    and a title, which really has nothing to adopt) from a file whose content
    the splitter failed to see. Deliberately crude and INDEPENDENT of the
    splitter: a corroboration check that reused the splitter would agree with it
    by construction and could not corroborate anything.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # A heading, of any level, including the ISO provenance markers.
            continue
        return True
    return False


class EnumerationDefect(Exception):
    """Raised when content went in and no candidates came out.

    Deliberately an exception rather than a return value. It runs inside the
    BEGIN edge's transaction, so raising rolls back the run row AND the mode
    change together, leaving the project exactly where it started. A return
    value would have to be checked by a caller that currently treats falsy as
    "nothing to adopt", which is the reading this whole guard exists to prevent.
    """


def enumerate_for_run(
    db: Session, *, project: Project, run: MemoryTransitionRun
) -> int:
    """DWB-593's BEGIN edge calls this. Returns the number of candidate rows.

    Contract, fixed by the caller in app/services/project.py:
      * writes rows with run_id, project_id, agent_id, state=pending, excerpt
      * does NOT stamp `enumerated_at` and does NOT touch the run's state;
        the caller does both after this returns, so ordering lives in one place
      * does NOT commit; the router owns the transaction
      * returns 0 ONLY when there is genuinely nothing to adopt, because the
        caller reads 0 as "cut straight through to the far side"

    Raises EnumerationDefect when any agent's file had content the splitter
    could not turn into candidates, or could not be read. Returning 0 in that
    case would seal a project whose agents have memory.
    """
    result = enumerate_candidates(db, project, run, persist=True)

    if result.is_defective:
        detail = []
        if result.content_without_candidates:
            detail.append(
                "produced no candidates despite having content: "
                + ", ".join(result.content_without_candidates)
            )
        if result.unreadable:
            detail.append("could not be read: " + ", ".join(result.unreadable))
        raise EnumerationDefect(
            "Enumeration refused: zero candidates is only safe when the source "
            "is genuinely empty, and it is not. "
            + "; ".join(detail)
            + ". This is a splitter or filesystem defect, not a project with "
            "nothing to adopt; cutting over here would seal a store whose "
            "agents still have memory. Nothing has been changed."
        )

    return result.candidate_count


def plan(db: Session, project: Project) -> Enumeration:
    """DRY RUN: what an adoption WOULD enumerate, with nothing persisted.

    DWB-594: "show the whole plan before anything is written. Every candidate,
    its proposed tier, and what the resulting store would look like, with
    nothing persisted."

    Callable BEFORE the transition starts, which is the useful moment. A plan
    you can only see after committing to the work answers the question too late:
    the reason to look is to decide whether to begin.

    There is no proposed tier, and that is not an omission. Spec section 4 rules
    that the snapshot makes no judgement, so the plan shows what will be ASKED,
    not what will be answered. A plan that guessed the tiers would be the
    rubber-stamp the whole design exists to prevent - an agent shown a proposed
    answer agrees with it.

    The run it passes through is UNSAVED and never added to the session: the
    enumerator needs one for `run_id`, and on a dry run those rows are built in
    memory and discarded. Creating a real run here would leave an open
    transition nobody started.
    """
    return enumerate_candidates(
        db, project, MemoryTransitionRun(project_id=project.id), persist=False
    )
