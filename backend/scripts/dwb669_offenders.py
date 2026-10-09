#!/usr/bin/env python3
# Path: backend/scripts/dwb669_offenders.py
# File: dwb669_offenders.py
# Created: 2026-10-09 (DWB-669)
# Purpose: Run the DWB-669 subject rule over the WHOLE live scar corpus and emit
#          a per-owner cleanup list, split into rows that survive the drop and
#          rows that fall below the match floor and need a replacement term
#          written by their owner. Read-only; writes nothing, ever.
# Caller: a human or an agent, from backend/ so .env resolves:
#            .venv/bin/python scripts/dwb669_offenders.py
#            .venv/bin/python scripts/dwb669_offenders.py --simulate-recall
# Callees: app.database, app.models.agent, app.models.agent_memory,
#          app.services.keyword_reachability (fires_without_subject),
#          app.services.memory_consult (the pure half), app.services.memory_scan
# Data In: nothing but the live store
# Data Out: stdout only
# Last Modified: 2026-10-09 (DWB-669)

"""The uniform sweep. It exists because three people wrote denylists first.

WHY NOT A HAND-PICKED LIST OF ROWS. Five rows were named from one set of 20
negative controls and cleaned. The owner of the first one then pointed out that
the same row still carried `all agents`, a synonym for the term just removed,
added in the same pass, identical in every respect that matters. The row read as
fixed and the junk route was still open. Two more people produced their own
lists afterwards and both caught themselves doing the same thing: one derived 17
offenders from which of her 26 controls happened to trip, withdrew them on
noticing, and re-derived a substantially larger set from the RULE instead.

A denylist fixes the instances your controls caught. It cannot fix the class, and
every one of these lists read as complete to the person holding it. So the rule
runs over all of it, once, uniformly, and the output IS the cleanup.

TWO BUCKETS, AND THE SECOND ONE IS NOT A DELETION JOB. Dropping a keyword can
take a row below `_MATCH_TOKENS_REQUIRED`, at which point the row cannot be
recalled by anything - a worse outcome than the junk it was firing, and an
invisible one, because the row still looks populated. Those rows need a
REPLACEMENT TERM written by the agent that owns them. Emitting one
undifferentiated list would have owners delete their way into a corpus of dead
rows, and the recall drop would show up later with no obvious cause.

A FRESH CONNECTION, ALWAYS. This opens its own Session and closes it. A
long-lived session on this MySQL reads inside one REPEATABLE READ snapshot, and
`expire_all()` re-SELECTs inside that same snapshot rather than escaping it - so
a verification run reusing an old connection reports a removal that landed as
still present. That already happened once during this cleanup, to the author of
the memory that records it.
"""

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.agent_memory import AgentMemory  # noqa: E402
from app.services import memory_consult  # noqa: E402
from app.services.keyword_reachability import fires_without_subject  # noqa: E402
from app.services.memory_scan import SCAR_FAMILY  # noqa: E402

FLOOR = memory_consult._MATCH_TOKENS_REQUIRED

# DEMONSTRATED POSITIVES. Every entry was shown firing on a real unrelated
# sentence by the agent who owned the row, and handed over rather than used -
# "a rule that cannot find a known positive passes its own sweep perfectly".
#
# THEY ARE LISTED HERE RATHER THAN COUNTED AS ABSENCE, which is the correction
# that makes the score honest. Eighteen of them were cleaned by hand BEFORE this
# sweep first ran, and they are plausibly the easiest ones - a control catches
# them, so a rule probably catches them too. A sweep scored only against what is
# still live would flatter itself by exactly the number somebody else already
# fixed. `--known-positives` reports both halves.
_DEMONSTRATED_POSITIVES = [
    # Removed by hand before the sweep, by their owners, under instruction.
    "show me", "before i", "every agent",
    "same file", "both files", "every write", "writing up", "hand over",
    "line range", "new file", "on its own", "two of us", "double check",
    "same result", "read the code", "what gets served", "one line", "one shot",
    "found nothing", "second scan",
    # Derived from the rule rather than from a control, and never touched. These
    # are the better test: nothing had flagged them, so nothing had fixed them.
    "ran twice", "common case", "never taken", "same answer", "sign off",
    "ground truth", "current shape", "already correct", "write it down",
    "read the output", "new prose",
    # Caught by the 20 project-vocabulary controls.
    "all agents", "what is left", "right now",
]


def _tokens_after(keywords, dropped):
    """Distinct matchable tokens a row would still carry after the drops."""
    keep = [k for k in keywords if k not in dropped]
    out = set()
    for k in keep:
        out |= memory_consult._keyword_tokens(k)
    return keep, out


def sweep(db):
    rows = (
        db.execute(
            select(AgentMemory)
            .where(AgentMemory.tier.in_(SCAR_FAMILY))
            .order_by(AgentMemory.agent_id, AgentMemory.id)
        )
        .scalars()
        .all()
    )
    names = {a.id: a.name for a in db.execute(select(Agent)).scalars().all()}
    survives = collections.defaultdict(list)
    strands = collections.defaultdict(list)
    total_offenders = 0
    for r in rows:
        kws = list(r.keywords or [])
        bad = [k for k in kws if isinstance(k, str) and fires_without_subject(k)]
        if not bad:
            continue
        total_offenders += len(bad)
        keep, tokens = _tokens_after(kws, set(bad))
        rec = (r.id, bad, keep, len(tokens))
        (survives if len(tokens) >= FLOOR else strands)[r.agent_id].append(rec)
    return rows, names, survives, strands, total_offenders


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--known-positives",
        action="store_true",
        help="report every demonstrated positive as LIVE or ALREADY REMOVED, so "
        "the rule is scored against the whole defect rather than against the part "
        "nobody had got to yet",
    )
    ap.add_argument(
        "--simulate-recall",
        action="store_true",
        help="also report what the frozen 30 would recall if every offender were "
        "dropped, so the cost is known BEFORE anyone edits a row",
    )
    args = ap.parse_args()

    db = SessionLocal()  # fresh connection, see module docstring
    try:
        rows, names, survives, strands, total = sweep(db)
        print(f"population    {len(rows)} scars (tier in SCAR_FAMILY)")
        print(f"floor         {FLOOR} distinct tokens")
        print(f"offenders     {total} keywords on "
              f"{sum(len(v) for v in survives.values()) + sum(len(v) for v in strands.values())} rows")
        print()

        for agent_id in sorted(set(survives) | set(strands)):
            print("=" * 72)
            print(f"OWNER {agent_id} {names.get(agent_id, '?')}")
            a = survives.get(agent_id, [])
            b = strands.get(agent_id, [])
            print(f"\n  BUCKET A - DROP ONLY. Row stays above the floor. ({len(a)} rows)")
            for mid, bad, keep, n in a:
                print(f"    #{mid}  drop {bad}")
                print(f"           keeps {keep}  -> {n} tokens")
            print(f"\n  BUCKET B - DROP AND REPLACE. Row falls to {FLOOR - 1} token(s) or "
                  f"fewer and can then be recalled by NOTHING. ({len(b)} rows)")
            for mid, bad, keep, n in b:
                print(f"    #{mid}  drop {bad}")
                print(f"           keeps {keep}  -> {n} tokens  ** NEEDS A NEW TERM **")
            print()

        if args.known_positives:
            print("=" * 72)
            print("DEMONSTRATED POSITIVES: does the rule find them, and are they live")
            live = {}
            for r in rows:
                for k in r.keywords or []:
                    if isinstance(k, str):
                        live.setdefault(k.strip().lower(), []).append((r.agent_id, r.id))
            missed = [k for k in _DEMONSTRATED_POSITIVES if not fires_without_subject(k)]
            still = [k for k in _DEMONSTRATED_POSITIVES if k in live]
            gone = [k for k in _DEMONSTRATED_POSITIVES if k not in live]
            print(f"  rule finds              {len(_DEMONSTRATED_POSITIVES) - len(missed)}"
                  f"/{len(_DEMONSTRATED_POSITIVES)}")
            if missed:
                print(f"  NOT FOUND BY THE RULE   {missed}   <- the rule is too narrow")
            print(f"  still live in the store {len(still)}")
            for k in still:
                print(f"     {k!r} on {live[k]}")
            print(f"  already removed by hand {len(gone)} - counted by name, not as absence")
            print(f"     {gone}")
            print()

        if args.simulate_recall:
            print("=" * 72)
            print("SIMULATED RECALL IF EVERY OFFENDER WERE DROPPED (nothing written)")
            sits = collections.defaultdict(list)
            tsv = Path(__file__).resolve().parent / "dwb667_situations.tsv"
            for ln in tsv.read_text().splitlines():
                if ln.startswith("#") or not ln.strip():
                    continue
                a_, s_ = ln.split("\t", 1)
                sits[int(a_)].append(s_)
            by_agent = {}
            for aid, ss in sorted(sits.items()):
                mine = [r for r in rows if r.agent_id == aid]
                fired = 0
                for s in ss:
                    toks = memory_consult._tokenize(s)
                    hit = False
                    for r in mine:
                        kws = [
                            k
                            for k in (r.keywords or [])
                            if not (isinstance(k, str) and fires_without_subject(k))
                        ]
                        matched = [
                            k
                            for k in kws
                            if (t := memory_consult._keyword_tokens(k)) and t <= toks
                        ]
                        n = len({t for k in matched for t in memory_consult._keyword_tokens(k)})
                        if n >= FLOOR:
                            hit = True
                            break
                    fired += 1 if hit else 0
                by_agent[aid] = (fired, len(ss))
                print(f"  agent {aid:>3} {names.get(aid,'?'):<12} {fired}/{len(ss)}")
            tot = sum(f for f, _ in by_agent.values())
            den = sum(d for _, d in by_agent.values())
            print(f"  TOTAL {tot}/{den}   (measured before the ban: 19/30 any)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
