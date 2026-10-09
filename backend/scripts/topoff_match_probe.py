#!/usr/bin/env python3
# Path: backend/scripts/topoff_match_probe.py
# File: topoff_match_probe.py
# Created: 2026-10-08 (DWB-644)
# Purpose: The forward instrument for the top-off scar consultation. Answers
#          "what would this situation recall, and why" against the live store
#          WITHOUT firing anything, so the match relation can be measured on
#          real rows with no risk of promoting a scar to CORE.
# Caller: a human or an agent, from backend/ so .env resolves:
#            .venv/bin/python scripts/topoff_match_probe.py --agent-id 38 \
#              "can I git checkout this file to undo my edit"
#            ... --stdin   reads one situation per line
# Callees: app.database, app.models.agent, app.models.agent_memory,
#          app.services.memory_consult (match_scars - the PURE half)
# Data In: an agent id, one or more situation strings
# Data Out: stdout only. Per situation: the match count, which author-written
#           keywords matched, and the population the count is over. Writes
#           nothing, to any table, ever.
# Last Modified: 2026-10-08 (DWB-644)

"""Measure the match relation forward, not from stored data.

DWB-644 criterion 3 asked for a forward instrument and ruled out a
retrospective hit rate, correctly: there is no corpus of real prompts in the
database, by design, and the only stored phrases are the Layer 1 catalogue
triggers, which are a ritual vocabulary rather than a prompt sample. Running
those through the matcher returns a number that is about the catalogue and not
about anything a user types.

IT CALLS `match_scars`, THE PURE HALF, AND THAT IS THE WHOLE SAFETY STORY.
`consult_scars` matches and then fires; `match_scars` only matches and contains
no write site. The split is structural rather than a flag, so this script
cannot promote a scar to CORE by being run against the live store - not because
it passes the right argument, but because the write does not exist on the path
it calls. A test asserts that property (tests/test_topoff_match_relation_dwb644
::TestMatchScarsCannotFire) so a later edit cannot quietly reintroduce it.

IT STILL ASSERTS ITS OWN PRECONDITIONS AND PRINTS WHAT WENT IN. A probe that
drives a system into a start state proves that state in the probe: the agent
exists, it has scars, and the sum of `fired_count` is identical before and
after the run. Without the last one a reader cannot tell this from a tool that
fired everything it touched.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.agent_memory import AgentMemory  # noqa: E402
from app.services import memory_consult  # noqa: E402
from app.services.memory_scan import SCAR_FAMILY  # noqa: E402


def _scar_population(db, agent_id: int):
    """The rows `consult_scars` actually searches, and nothing wider.

    `tier.in_(SCAR_FAMILY)` is a single-element tuple since DWB-611: CORE is
    NOT searched. Any denominator that includes it is the wrong population, and
    a count without its population stated beside it is not comparable to
    anyone else's count.
    """
    return list(
        db.execute(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent_id)
            .where(AgentMemory.tier.in_(SCAR_FAMILY))
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )


def _fired_total(db, agent_id: int) -> int:
    return (
        db.execute(
            select(func.coalesce(func.sum(AgentMemory.fired_count), 0)).where(
                AgentMemory.agent_id == agent_id
            )
        ).scalar_one()
        or 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read one situation per line from stdin instead of argv",
    )
    parser.add_argument("situations", nargs="*")
    args = parser.parse_args()

    situations = (
        [ln.rstrip("\n") for ln in sys.stdin if ln.strip()]
        if args.stdin
        else list(args.situations)
    )
    if not situations:
        parser.error("no situations given - pass them as arguments or use --stdin")

    db = SessionLocal()
    try:
        agent = db.get(Agent, args.agent_id)
        if agent is None:
            print(f"PRECONDITION FAILED: no agent {args.agent_id}")
            return 1
        scars = _scar_population(db, args.agent_id)
        unmatchable = [
            s
            for s in scars
            if len(memory_consult.keyword_token_set(s))
            < memory_consult._MATCH_TOKENS_REQUIRED
        ]
        fired_before = _fired_total(db, args.agent_id)

        print(f"agent         {agent.id} {agent.name}")
        print(f"population    {len(scars)} scars (tier in SCAR_FAMILY; CORE not searched)")
        print(f"unmatchable   {len(unmatchable)} (fewer than "
              f"{memory_consult._MATCH_TOKENS_REQUIRED} keyword tokens, can never match)")
        print(f"fired total   {fired_before} (before)")
        if not scars:
            print("PRECONDITION FAILED: no scars - every number below would "
                  "measure nothing")
            return 1

        fired_situations = 0
        for situation in situations:
            try:
                result = memory_consult.match_scars(
                    db, agent_id=args.agent_id, situation=situation
                )
            except memory_consult.ConsultError as exc:
                print(f"\n  REFUSED ({exc.code})  {situation[:70]!r}")
                continue
            if result["count"]:
                fired_situations += 1
            print(
                f"\n  matched={result['count']:3d}  tokens={result['situation_tokens']:3d}"
                f"  {situation[:70]!r}"
            )
            for memory_id, keywords in result["matched_keywords"].items():
                row = db.get(AgentMemory, memory_id)
                line = (row.condensed or row.body or "").replace("\n", " ")
                print(f"        #{memory_id} {keywords} :: {line[:76]!r}")

        print(
            f"\nhit rate      {fired_situations}/{len(situations)} situations "
            f"recalled at least one scar"
        )

        # POSTCONDITION. Without it this output is indistinguishable from a
        # tool that fired every row it reported.
        db.expire_all()
        fired_after = _fired_total(db, args.agent_id)
        print(f"fired total   {fired_after} (after)")
        if fired_after != fired_before:
            print("ABORT: THIS PROBE WROTE SOMETHING. It must not be able to.")
            return 1
        print("wrote nothing: confirmed")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
