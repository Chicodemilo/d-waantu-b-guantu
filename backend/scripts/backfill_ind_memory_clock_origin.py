#!/usr/bin/env python3
# Path: scripts/backfill_ind_memory_clock_origin.py
# File: backfill_ind_memory_clock_origin.py
# Created: 2026-10-07
# Purpose: Idempotent data backfill for agent_memories rows that have no clock origin - both created_session_id and last_reinforced_session_id NULL - which memory_score reports as `no_session_origin`, leaving band null and memory_context with nothing to assemble. Fills created_session_id ONLY, from an origin session the caller names explicitly.
# Caller: Manual CLI
# Callees: app.database.SessionLocal, app.models.agent.Agent, app.models.project.Project, app.models.agent_memory.AgentMemory, app.models.dwb_session.DwbSession
# Data In: CLI args (--project-prefix, --origin-session-id, --include-raw, --apply); agent_memories / agents / dwb_sessions rows
# Data Out: stdout report; UPDATE of agent_memories.created_session_id when --apply
# Last Modified: 2026-10-07

"""Give orphaned memory rows a point on the session clock.

WHY A ROW CAN HAVE NO ORIGIN. `memory_score.sessions_since_reinforced` counts
closed DWB sessions since COALESCE(last_reinforced_session_id,
created_session_id). With both NULL there is no origin, it returns None, the
row is reported `scored: false` / `no_session_origin` with a null band, and
`memory_context.assemble_session_context` finds nothing to put in either band,
so `memory_mode.memory_full_for` falls back to the sealed pointer. An agent
with a full store spawns with none of it.

The reachable cause is a write made while no DWB session was open for the
project: the write is accepted and created_session_id lands NULL. On IND that
happened to an entire adoption run, because the run was driven from another
project's session.

WHY THE ORIGIN IS AN ARGUMENT AND NOT A LOOKUP. The honest origin for a row
written INSIDE a session is that session, and this script would not be needed
for it. These rows were written in a GAP between sessions, so no window
contains them and there is nothing to look up. Which session they should count
from is a judgement about the decay curve - it is made by a human, stated once,
and passed in here. A script that guessed would bury that judgement in code
where nobody would find it again.

THE VALUE THIS WRITES IS A FLOOR, NOT A BIRTH CERTIFICATE. SAID PLAINLY
BECAUSE IT IS THE ONE THING A LATER READER CANNOT RECOVER FROM THE ROW. On
IND the chosen origin was session 2651, and no row stamped 2651 was created
during 2651: that session closed at 13:51:52 and the adoption burst ran from
14:15:21 to 15:20:19, in the gap before 2653 opened. 2651 is the LAST KNOWN
TICK OF THE CLOCK BEFORE THE ROWS EXISTED, which is the correct thing to
count from, and it is not a true statement about when the row was written.

The column tolerates this because of what it is FOR: `created_session_id` is
consumed by `memory_score.sessions_since_reinforced` as a clock origin, under
a strict `DwbSession.id > origin`, so the origin session is excluded from the
gap and the first session counted is the next one. For a backfilled row that
is exactly right - it did not exist during 2651, and 2653 onward IS genuine
experience for it. Read as provenance, the same value is wrong. Anyone
auditing where a memory came from should use `created_at` and the
`memory_transitions` run, never this column on a backfilled row.

The alternative was the next session to OPEN after the burst (2653 on IND).
It is rejected and the reason is recorded so it is not re-proposed: the strict
comparison would exclude 2653 from every future count, and these rows
demonstrably existed before 2653 opened, so it under-counts the decay by one
session permanently.

ONLY created_session_id IS WRITTEN. Not last_reinforced_session_id, which means
"this memory fired and was reinforced" and did not happen; not tier, body,
context_key or fired_count. A row with an untouched last_reinforced_session_id
and a filled created_session_id reads correctly: it has a birth and has never
been reinforced.

RAW ROWS ARE EXCLUDED BY DEFAULT AND INCLUDED ONLY ON --include-raw.
`raw`/untiered is the correct state for a row awaiting consolidation, not a
defect, and memory_score reports it as `untiered` for its own reason. Filling
an origin on a raw row changes NOTHING observable today: `_entry()` returns on
the tier check before it ever calls `sessions_since_reinforced`, so the row
reports `untiered` either way and no band moves.

That is exactly why the flag exists rather than the behaviour being on by
default. A raw row with no origin is not fresh-and-fine, it is fresh AND
carrying no clock, and those two report identically. The damage is deferred to
the moment consolidation tiers it, at which point it is served with a wrong
decay curve and nothing marks it out from a correctly-originated row. Filling
it now is cheap and prevents that; it just cannot be PROVEN now by any read,
which is the thing to say out loud when running with this flag rather than
quietly substituting a weaker proof.

Idempotent. The selection predicate is "origin still NULL", so a second run
finds nothing and writes nothing.

Usage:
    python backend/scripts/backfill_ind_memory_clock_origin.py \
        --project-prefix IND --origin-session-id 2651              # dry run
    python backend/scripts/backfill_ind_memory_clock_origin.py \
        --project-prefix IND --origin-session-id 2651 --apply      # write
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbSession
from app.models.project import Project


def _target_rows(
    db: Session, agent_ids: list[int], include_raw: bool = False
) -> list[AgentMemory]:
    """Rows with no clock origin at all; untiered ones only on include_raw.

    Both columns are checked, not just created_session_id. A row reinforced but
    never given a birth session HAS an origin as far as the score is concerned
    (the COALESCE picks last_reinforced first), so it is not broken and must not
    be rewritten.
    """
    if not agent_ids:
        return []
    where = [
        AgentMemory.agent_id.in_(agent_ids),
        AgentMemory.created_session_id.is_(None),
        AgentMemory.last_reinforced_session_id.is_(None),
    ]
    if not include_raw:
        where.append(AgentMemory.tier != MemoryTier.raw)
    return list(
        db.execute(
            select(AgentMemory).where(*where).order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )


def _report(label: str, rows: list[AgentMemory], names: dict[int, str]) -> None:
    per = defaultdict(lambda: defaultdict(int))
    for row in rows:
        per[row.agent_id][row.tier.value] += 1
    print(f"{label}: {len(rows)} row(s)")
    for agent_id in sorted(per):
        tiers = ", ".join(f"{t}={n}" for t, n in sorted(per[agent_id].items()))
        total = sum(per[agent_id].values())
        print(f"    agent {agent_id:>5} {names.get(agent_id, '?'):<16} {total:>4}  ({tiers})")


def backfill(
    db: Session,
    prefix: str,
    origin_session_id: int,
    apply: bool,
    include_raw: bool = False,
) -> int:
    project = db.execute(
        select(Project).where(Project.prefix == prefix)
    ).scalar_one_or_none()
    if project is None:
        raise SystemExit(f"no project with prefix {prefix!r}")

    origin = db.get(DwbSession, origin_session_id)
    if origin is None:
        raise SystemExit(f"dwb_session {origin_session_id} does not exist")
    if origin.project_id != project.id:
        # Refused rather than warned. The clock these rows decay against is
        # their own project's sessions; an origin belonging to another project
        # produces arithmetic that happens to work and a row that lies about
        # where it came from.
        raise SystemExit(
            f"dwb_session {origin_session_id} belongs to project "
            f"{origin.project_id}, not {prefix} (project {project.id})"
        )
    if origin.closed_at is None:
        # An open session is the one currently happening. Counting from it is
        # legitimate for a row born inside it; as a backfill origin it means the
        # gap cannot start counting until this session closes, which is not what
        # anyone intends when repairing history.
        raise SystemExit(
            f"dwb_session {origin_session_id} is still open; pick a closed session"
        )

    agents = list(
        db.execute(select(Agent).where(Agent.project_id == project.id)).scalars().all()
    )
    names = {a.id: a.name for a in agents}
    agent_ids = sorted(names)

    print(f"project {project.prefix} (id={project.id}), memory_mode={project.memory_mode.value}")
    print(
        f"origin session {origin.id}: opened {origin.opened_at}, closed {origin.closed_at}"
    )
    print(f"agents in scope: {len(agent_ids)}")
    print()

    scope = "any tier" if include_raw else "tier != raw"
    before = _target_rows(db, agent_ids, include_raw)
    _report(f"BEFORE (rows with no clock origin, {scope})", before, names)
    before_ids = {row.id for row in before}

    if not before:
        print("\nnothing to do.")
        return 0

    if not apply:
        print(f"\nDRY RUN. {len(before)} row(s) would get created_session_id={origin.id}.")
        print("re-run with --apply to write.")
        return 0

    touched = 0
    for row in before:
        row.created_session_id = origin.id
        touched += 1
    if touched != len(before_ids):
        raise SystemExit(f"assigned {touched} but selected {len(before_ids)}; aborting")
    db.commit()

    # Verify the POSITIVE set, not only the absence. "Zero rows left unfixed"
    # is also what a run that enumerated nothing reports, so the set of ids now
    # carrying this origin is asserted to be exactly the set selected.
    db.expire_all()
    after = _target_rows(db, agent_ids, include_raw)
    _report(f"\nAFTER (rows still with no clock origin, {scope})", after, names)

    landed = set(
        db.execute(
            select(AgentMemory.id).where(
                AgentMemory.agent_id.in_(agent_ids),
                AgentMemory.created_session_id == origin.id,
            )
        )
        .scalars()
        .all()
    )
    missing = before_ids - landed
    print(f"\nrows written: {touched}")
    print(f"rows now carrying created_session_id={origin.id}: {len(landed)}")
    if missing:
        raise SystemExit(f"{len(missing)} selected row(s) did not land: {sorted(missing)[:20]}")
    if after:
        print(f"WARNING: {len(after)} row(s) still have no origin (see breakdown above)")
    return touched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-prefix", default="IND")
    parser.add_argument(
        "--origin-session-id",
        type=int,
        required=True,
        help="closed dwb_sessions.id of the project these rows should count from",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="also fill untiered (raw) rows; nothing observable changes today, see module docstring",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write; omitted means dry run",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        backfill(
            db,
            args.project_prefix,
            args.origin_session_id,
            args.apply,
            args.include_raw,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
