#!/usr/bin/env python3
# Path: scripts/dwb620_repair_adopted_memory.py
# File: dwb620_repair_adopted_memory.py
# Created: 2026-10-01 (DWB-620)
# Purpose: One-shot repair for THIS install's adopted memory - correct every
#          context_key invented by the old splitter, THEN stamp the session
#          origin that decide() failed to write. The order is load-bearing and
#          is enforced structurally, not by comment.
# Caller: a human, by hand, once. Not a migration and not called from app code.
# Callees: app.services.memory_format (the FIXED splitter), app.models.agent_memory,
#          app.models.agent, app.models.project, app.models.dwb_session
# Data In: --project-id, the on-disk .dwb/memory/<prefix>/<name>/memory.md files
# Data Out: a printed plan or an applied repair; exit 0 on success, 1 on refusal
# Last Modified: 2026-10-01 (DWB-620)

"""Repair the rows that adoption wrote wrong, in the one order that is safe.

WHY A SCRIPT AND NOT A MIGRATION. Correcting `context_key` requires recomputing
the heading chain from the on-disk `memory.md` files, and no other install can
be assumed to have them. It also does not need to: every other project is
`stock`, so DWB is the only install that has ever adopted, and any install that
adopts after DWB-620 lands gets correct rows from the two code fixes and never
runs this.

THE ORDER IS THE WHOLE DESIGN, AND BOTH STEPS LOOK INDEPENDENTLY SAFE.

    1. correct context_key      (from the fixed splitter, matched by body)
    2. THEN stamp created_session_id on rows WHERE it IS NULL

Reversed, this DELETES LESSONS. The stamp is what makes a row scoreable;
a scoreable scar can reach the at-rest set; `memory_scan` pulls any
ticket-shaped string out of a `context_key`; a context resolving to a CLOSED
ticket makes the row `finished`; and `memory_scar_conclude` journals that row
and then deletes it. 17 live rows carry `DWB-520` inside a mangled timestamp
and that ticket is `done`. The chain is dormant today ONLY because every
adopted row is unscoreable - which means THE FIX FOR THE OUTAGE IS THE ACT THAT
ARMS IT. That is why the dangerous step is the one that looks like the point of
the ticket.

So the ordering is not left to the caller and not left to a comment above two
calls. `_stamp_origins` cannot be called without a `Correction`, and only
`_correct_context_keys` constructs one. Skipping step 1 is not a mistake a
future caller can make by writing the calls in the wrong order; it is
unrepresentable. Between the two, `_verify_no_armed_rows` re-reads the database
and REFUSES the stamp if any row that is about to become scoreable still
carries a provenance-shaped context_key.

SCOPE THE STAMP BY NULLITY, NEVER BY COUNT. The store held 396 adopted rows and
holds 402 now: six were written through the raw append path, which stamps the
origin correctly, and three of those are the author's. A blanket update sized
from a remembered count overwrites them. Every write below is scoped by
`created_session_id IS NULL`, so a row that already has an origin is invisible
to this script no matter how many such rows exist.

IDEMPOTENT. Step 1 recomputes the same value from the same file; step 2 sees no
NULL rows on a second pass. Running it twice reports zero changes the second
time, which a plain run after an `--apply` will show.

THE DRY RUN TAKES THE SAME PATH AND DIFFERS ONLY IN COMMIT VERSUS ROLLBACK.
This was worth getting wrong once to see. The first version of this script made
`apply` decide whether the rows were MUTATED, so on a dry run the gate re-read
an uncorrected database, refused, and step 2 was never rehearsed - the dry run
could not reach the half of the script that does the dangerous thing, and a
rehearsal that cannot reach the dangerous step is not a rehearsal. Now both
steps always mutate the session, the gate always re-reads them, and `--apply`
chooses only whether that transaction is committed or rolled back. One path,
exercised identically either way.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.agent_memory import AgentMemory, MemoryTier  # noqa: E402
from app.models.dwb_session import DwbSession  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.services import memory_format  # noqa: E402

# A context_key the old splitter invented from a write-stamp. No writer in the
# app produces a context_key that opens with a date-time: the raw path takes
# whatever the agent passed, and the decide path takes a heading chain. So this
# shape is diagnostic of the defect rather than merely suspicious.
PROVENANCE_SHAPED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

# Tiers that are reachable by the scoring machinery. `raw` has no curve and is
# excluded from every candidate list regardless of its origin, so a raw row
# cannot be armed by the stamp and is not part of the verification gate.
SCOREABLE_TIERS = (MemoryTier.scar, MemoryTier.working, MemoryTier.core)


@dataclass
class Plan:
    """What one row would have done to it, and why. Printed, not inferred."""

    memory_id: int
    agent_name: str
    field: str
    before: object
    after: object
    reason: str


@dataclass
class Correction:
    """THE RECEIPT FOR STEP 1, AND THE REASON STEP 2 CANNOT RUN WITHOUT IT.

    This exists to carry a precondition in the type rather than in a comment.
    `_stamp_origins` takes one of these, and only `_correct_context_keys`
    returns one, so there is no call sequence that stamps an origin onto a row
    whose context_key has not been recomputed first. A future caller cannot
    reorder the two steps without first inventing a Correction, which is a
    deliberate act rather than an oversight.
    """

    plans: list[Plan] = field(default_factory=list)
    applied: bool = False
    agents_seen: int = 0
    files_missing: list[str] = field(default_factory=list)
    unmatched_rows: int = 0
    ambiguous_bodies: list[str] = field(default_factory=list)


def _memory_md_path(project: Project, agent: Agent) -> Path:
    return (
        Path(project.repo_path)
        / ".dwb"
        / "memory"
        / project.prefix
        / agent.name
        / "memory.md"
    )


def _chain_by_body(text: str) -> tuple[dict[str, tuple[str, ...]], set[str]]:
    """Map each entry body to its heading chain, under the FIXED splitter.

    Returns the map plus the set of bodies that are ambiguous - the same text
    appearing under two DIFFERENT chains. Those are reported and skipped rather
    than guessed at: picking one would be a coin flip recorded as a repair.
    A body repeated under the SAME chain is not ambiguous, because every
    candidate answer agrees.
    """
    seen: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for entry in memory_format.split(text).entries:
        seen[entry.body].add(entry.heading_path)
    chains = {b: next(iter(p)) for b, p in seen.items() if len(p) == 1}
    ambiguous = {b for b, p in seen.items() if len(p) > 1}
    return chains, ambiguous


def _correct_context_keys(db, project: Project) -> Correction:
    """STEP 1. Recompute every adopted row's context_key from its flat file.

    Matched BY BODY, which is what survives the adopt round trip: decide()
    stored `split(render(entry))[0].body`, so the stored body is the flat file's
    body. A row whose body matches no entry in the file is left ALONE unless its
    context_key is provenance-shaped - nothing but the old splitter produces
    that shape, so clearing it is safe even without a matching entry, and
    leaving it would leave the eviction chain armed on a row the match missed.
    """
    correction = Correction()

    agents = db.execute(
        select(Agent).where(Agent.project_id == project.id).order_by(Agent.id)
    ).scalars().all()

    for agent in agents:
        rows = db.execute(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent.id)
            .order_by(AgentMemory.id)
        ).scalars().all()
        if not rows:
            continue
        correction.agents_seen += 1

        path = _memory_md_path(project, agent)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # The flat file is the ONLY source of truth for the correct chain.
            # Without it nothing can be recomputed for this agent, so say so
            # loudly and correct nothing rather than defaulting to NULL, which
            # would read as "deliberately context-free".
            correction.files_missing.append(str(path))
            continue

        chains, ambiguous = _chain_by_body(text)
        correction.ambiguous_bodies.extend(sorted(ambiguous))

        for row in rows:
            if row.body in ambiguous:
                continue
            if row.body in chains:
                # PARITY WITH THE WRITER, NOT "every row gets its chain".
                # memory_decide.decide sets context_key ONLY for `scar` (DWB-611:
                # every scar is context-bound; the column means nothing outside
                # that tier and a value there would read as a binding the SCAN
                # should test). A repair that handed every working row its
                # heading would not be correcting adoption, it would be
                # overwriting a deliberate decision with a different one - 33
                # rows on this install, every one of them a clobber. The repair
                # produces exactly what a FIXED decide() would have produced.
                chain = chains[row.body]
                want = (
                    " / ".join(chain)
                    if row.tier == MemoryTier.scar and chain
                    else None
                )
                reason = "recomputed from the flat file with the fixed splitter"
            elif (
                row.tier == MemoryTier.scar
                and row.context_key
                and PROVENANCE_SHAPED.match(row.context_key)
            ):
                want = None
                reason = (
                    "no matching entry in the flat file, but the key is a "
                    "write-stamp the old splitter invented"
                )
            else:
                correction.unmatched_rows += 1
                continue

            if row.context_key == want:
                continue
            correction.plans.append(
                Plan(row.id, agent.name, "context_key", row.context_key, want, reason)
            )
            # Always mutated, never conditionally: the caller decides commit or
            # rollback. See the module docstring on why a dry run that skips the
            # write cannot rehearse the gate or step 2.
            row.context_key = want

    return correction


def _verify_no_armed_rows(db, project: Project) -> list[int]:
    """THE GATE BETWEEN THE TWO STEPS. Re-reads, never trusts step 1's own word.

    Returns the ids of rows that are about to become scoreable while still
    carrying a provenance-shaped context_key. A non-empty list means the stamp
    MUST NOT run: those are exactly the rows the eviction chain would reach.
    Step 1 reporting success is not evidence it landed, which is the whole
    failure family this lane keeps producing.
    """
    rows = db.execute(
        select(AgentMemory.id, AgentMemory.context_key)
        .join(Agent, Agent.id == AgentMemory.agent_id)
        .where(
            Agent.project_id == project.id,
            AgentMemory.created_session_id.is_(None),
            AgentMemory.tier.in_(SCOREABLE_TIERS),
        )
    ).all()
    return [
        rid
        for rid, key in rows
        if key is not None and PROVENANCE_SHAPED.match(key) is not None
    ]


def _origin_for(db, project: Project, created_at) -> int | None:
    """The DWB session this row was written during.

    The session whose window CONTAINS `created_at`, else the latest session
    opened at or before it. Both are statements about when the row was created,
    which is what the column means and what the raw append path records. The
    adopted rows were all written inside one still-open session, so in practice
    this resolves to that session - but the rule is written to be true in
    general rather than tuned to tonight's data.
    """
    inside = db.execute(
        select(DwbSession.id)
        .where(
            DwbSession.project_id == project.id,
            DwbSession.opened_at <= created_at,
            (DwbSession.closed_at.is_(None)) | (DwbSession.closed_at >= created_at),
        )
        .order_by(DwbSession.id.desc())
        .limit(1)
    ).scalar()
    if inside is not None:
        return inside
    return db.execute(
        select(DwbSession.id)
        .where(
            DwbSession.project_id == project.id,
            DwbSession.opened_at <= created_at,
        )
        .order_by(DwbSession.id.desc())
        .limit(1)
    ).scalar()


def _stamp_origins(db, project: Project, correction: Correction):
    """STEP 2. Give every origin-less row the session it was written in.

    Takes a `Correction` it does not read, and that is the point: the parameter
    is a precondition made structural. See the Correction docstring.

    SCOPED BY NULLITY. The filter is `created_session_id IS NULL`, so rows the
    raw path already stamped are invisible here regardless of how many there
    are. Never size this by a remembered row count.
    """
    assert isinstance(correction, Correction), (
        "step 2 requires the receipt from step 1 - see the module docstring on "
        "why reversing these deletes lessons"
    )

    plans: list[Plan] = []
    rows = db.execute(
        select(AgentMemory, Agent.name)
        .join(Agent, Agent.id == AgentMemory.agent_id)
        .where(
            Agent.project_id == project.id,
            AgentMemory.created_session_id.is_(None),
        )
        .order_by(AgentMemory.id)
    ).all()

    for row, agent_name in rows:
        origin = _origin_for(db, project, row.created_at)
        if origin is None:
            # No session to attribute it to. Leaving it NULL keeps it
            # unreachable, which is the outage - but inventing an origin is
            # worse, because the decay clock would then count from a session
            # this row was not written in.
            continue
        plans.append(
            Plan(
                row.id,
                agent_name,
                "created_session_id",
                None,
                origin,
                "the DWB session open when the row was created",
            )
        )
        row.created_session_id = origin
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the repair. Without it the script only prints the plan.",
    )
    args = parser.parse_args()
    apply = args.apply

    db = SessionLocal()
    try:
        project = db.get(Project, args.project_id)
        if project is None:
            print(f"REFUSED: project {args.project_id} not found")
            return 1
        if not project.repo_path:
            print(f"REFUSED: project {project.prefix} has no repo_path")
            return 1

        mode = "APPLY" if apply else "DRY RUN"
        print(f"=== DWB-620 repair, {mode}, project {project.prefix} ({project.id})")

        print("\n--- step 1: correct context_key from the flat files")
        correction = _correct_context_keys(db, project)
        print(f"    agents with memory rows : {correction.agents_seen}")
        print(f"    context_key corrections : {len(correction.plans)}")
        for p in correction.plans:
            print(f"      mem {p.memory_id:4} {p.agent_name:12} {p.before!r} -> {p.after!r}")
        if correction.files_missing:
            print(f"    FLAT FILE UNREADABLE for: {correction.files_missing}")
        if correction.ambiguous_bodies:
            print(f"    ambiguous bodies skipped: {len(correction.ambiguous_bodies)}")
        print(f"    rows with no flat-file match, left alone: {correction.unmatched_rows}")

        db.flush()

        print("\n--- gate: no row may become scoreable while still provenance-bound")
        armed = _verify_no_armed_rows(db, project)
        if armed:
            db.rollback()
            print(f"    REFUSED. {len(armed)} row(s) still carry a write-stamp as")
            print(f"    their context_key: {armed}")
            print("    Nothing was written. Stamping these would arm the eviction")
            print("    chain described in the module docstring.")
            return 1
        print("    clear")

        print("\n--- step 2: stamp created_session_id WHERE it IS NULL")
        stamps = _stamp_origins(db, project, correction)
        print(f"    origin stamps : {len(stamps)}")
        by_session: dict[int, int] = defaultdict(int)
        for p in stamps:
            by_session[p.after] += 1
        for sid, n in sorted(by_session.items()):
            print(f"      session {sid}: {n} rows")

        if apply:
            db.commit()
            print("\nCOMMITTED")
        else:
            db.rollback()
            print("\nNOTHING WRITTEN (re-run with --apply)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
