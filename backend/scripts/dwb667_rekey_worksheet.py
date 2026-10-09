#!/usr/bin/env python3
# Path: backend/scripts/dwb667_rekey_worksheet.py
# File: dwb667_rekey_worksheet.py
# Created: 2026-10-09 (DWB-667)
# Purpose: Print ONE agent's unreachable scars so that agent can re-keyword its
#          own rows. Read-only. It shows the lesson and the current keywords and
#          deliberately PROPOSES NOTHING - DWB-654 forbids deriving a keyword
#          from a body, and a suggestion in this output would be derived from
#          one whether or not the author noticed.
# Caller: the OWNING agent, from backend/ so .env resolves:
#            .venv/bin/python scripts/dwb667_rekey_worksheet.py --agent-id 38
# Callees: app.database, app.models.agent, app.models.agent_memory,
#          app.services.memory_consult (keyword_token_set - the pure half),
#          app.services.memory_scan (SCAR_FAMILY)
# Data In: an agent id
# Data Out: stdout only. One block per scar, plus the curl to send. Writes
#           nothing, to any table, ever.
# Last Modified: 2026-10-09 (DWB-667)

"""The worksheet for a per-author re-keywording pass.

WHY A WORKSHEET AND NOT A BACKFILL. DWB-667's keywords have to be written by the
agent that learned the lesson, for the same reason `condensed` does: the route
is owner-only and there is no operator path. A script that proposed keywords
would be deriving them from the body, which DWB-654 rules out in plain words -
and a proposal is worse than a derivation, because the author would approve it
and the row would afterwards be indistinguishable from one they wrote.

So this prints the lesson and gets out of the way.

IT DOES NOT PRINT THE DWB-667 SITUATION SET, AND THAT IS DELIBERATE. The
after-number is measured over a frozen set of 30 situations in
backend/scripts/dwb667_situations.tsv. An author who has read that file and then
writes keywords is writing the answers to the test, and the measurement stops
being about recall and becomes about whoever wrote both sides. Do not open it
while you are doing your pass. It is published so a reader can check the
measurement afterwards, not so an author can aim at it.

WHAT MAKES A KEYWORD REACHABLE, repeated here because this is the surface an
author is actually looking at while deciding:

  The words that will be in the air when you are IN that situation, never a
  label for what the lesson is ABOUT. 'git checkout' and 'shared tree', not
  'revert-semantics'. You only know the moral after you have already remembered
  the lesson, so the moral cannot be the retrieval term.

  Every token of a keyword must be present and nothing is stemmed, so
  'ORM model edit' does not match "I edited an ORM model". Prefer two short
  concrete terms over one long precise one.

  Recall needs two distinct tokens across the whole set.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.agent_memory import AgentMemory  # noqa: E402
from app.services import memory_consult  # noqa: E402
from app.services.memory_scan import SCAR_FAMILY  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument(
        "--api",
        default="http://localhost:8000",
        help="base URL printed in the curl lines",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        agent = db.get(Agent, args.agent_id)
        if agent is None:
            print(f"PRECONDITION FAILED: no agent {args.agent_id}")
            return 1

        rows = list(
            db.execute(
                select(AgentMemory)
                .where(AgentMemory.agent_id == args.agent_id)
                .where(AgentMemory.tier.in_(SCAR_FAMILY))
                .order_by(AgentMemory.id.asc())
            )
            .scalars()
            .all()
        )
        fired_before = (
            db.execute(
                select(func.coalesce(func.sum(AgentMemory.fired_count), 0)).where(
                    AgentMemory.agent_id == args.agent_id
                )
            ).scalar_one()
            or 0
        )

        print(f"agent         {agent.id} {agent.name}")
        print(f"population    {len(rows)} scars (tier in SCAR_FAMILY)")
        print(f"fired total   {fired_before} (before)")
        if not rows:
            print("PRECONDITION FAILED: no scars - nothing to re-keyword")
            return 1
        print()
        print("Rewrite the keywords on each row below IN YOUR OWN WORDS, then send")
        print("the curl. The route refuses anything your own situation line does")
        print("not contain, so write the situation first and read the keywords out")
        print("of it. Do NOT open scripts/dwb667_situations.tsv while you do this.")
        print()

        for row in rows:
            tokens = memory_consult.keyword_token_set(row)
            state = (
                "UNMATCHABLE (fewer than "
                f"{memory_consult._MATCH_TOKENS_REQUIRED} tokens, cannot ever fire)"
                if len(tokens) < memory_consult._MATCH_TOKENS_REQUIRED
                else f"{len(tokens)} matchable tokens"
            )
            print("-" * 72)
            print(f"#{row.id}  tier={row.tier.value}  fired={row.fired_count}  {state}")
            print(f"  now:       {row.keywords}")
            print(f"  lesson:    {(row.condensed or '').strip()[:200]}")
            body = " ".join((row.body or "").split())
            print(f"  body:      {body[:300]}")
            print(
                f"  curl -s -X POST {args.api}/api/agents/{row.agent_id}"
                f"/memories/{row.id}/rekey \\\n"
                f"    -H 'X-Agent-ID: {row.agent_id}' -H 'Content-Type: application/json' \\\n"
                f"    -d '{json.dumps({'keywords': ['<term>', '<term>'], 'situation': '<the moment, in your words>'})}'"
            )

        print("-" * 72)
        print(f"{len(rows)} rows. Nothing was written by this script.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
