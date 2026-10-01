# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-10-01, pushed and green)

**HEAD `ed50c3d`, pushed to master. 2934 passed, 0 failed**, taken on a tree whose
content fingerprint was identical before and after the run. Three commits tonight:
`b137bb5` (the human_memory lane), `3dea6b3` (ten defects), `ed50c3d` (the memory
sorting mechanism, withdrawal, and the timestamp asymmetry).

Seventeen tickets closed, DWB-617 through DWB-636. Working tree clean.

## READ THIS BEFORE THE NEXT SESSION STARTS

**Closing a session starts a clock that has never run.** Every memory row shares one
origin session because the whole catalogue was adopted inside it. Nothing has decayed,
nothing has reached a floor, and no eviction has ever had a candidate. When sessions
accumulate, rows reach their floors **in lockstep** rather than gradually.

That is not dangerous now - DWB-626 fixed the deletion path that would have failed on
every candidate at once - but it means the first consolidation sweeps after tonight do
real work for the first time. Watch what they do rather than assuming they do nothing.

**Memory writes go to `POST /api/agents/{id}/memories`.** `session-complete` is sealed
under human_memory and returns 409. The playbook still documents only the sealed
endpoints, so a worker following it at close gets 409 then 422 (`cost` is
`none|low|high`, `caught_by` is `me|worker|human|ci`, not prose) and may conclude their
write failed. **Fix the playbook early next session** - it hits people at the moment
they are trying to leave.

## What was actually wrong, and what tonight established

The lane shipped working and three days of use found what no test could.

**Nothing sorted the memories agents write.** The spec assigns that to consolidation at
the session boundary. Consolidation runs at startup, performs four other movements, and
never looked. So a docstring promised tiering, the promise read as a description, and 39
real lessons sat unscoreable and unreachable. Now tiered from the write-time tags, with
unjudged notes defaulting *down* to working - which is the safety mechanism, not a
preference, because a working row is structurally outside the set that can be
auto-promoted to the tier that never decays.

**A memory could not be withdrawn.** No PATCH, no DELETE, anywhere. A lesson known to be
wrong was permanent. Worse, the two existing retirement paths could not delete an adopted
row at all - they raised on a foreign key and the failure was swallowed inside a
catch-and-log where a hard failure and a clean no-op render identically.

**Timestamps could store out of order.** A value carrying a fraction rounds up on
storage; one generated at second precision does not. So a decision could record itself
half a second in the future while a row created after it stored earlier. Five column
pairs, four of them feeding the session rollup - the system measuring its own work.

## The design questions that are genuinely yours

1. **A distinct human identity at the API.** There is no human actor. `award_human_score`
   authenticates nothing; the human acts through an agent's id. This surfaced when
   withdrawal was specified as "the owning agent plus the human" and Barry_DWB correctly
   refused to invent an auth scheme to satisfy a clause, rather than make a security
   decision in passing. Unticketed.
2. **DWB-632 fixes the mechanism and builds neither the SCAN (spec section 2) nor any way
   for an agent to re-judge a tier it disagrees with.** Both are named under a NOT BUILT
   heading in that ticket, deliberately: the inference that a working mechanism means
   section 4 is finished is exactly how the original defect survived.

## Open tickets

- **DWB-636** - a consolidation failure is swallowed and reads identically to a clean
  no-op. The only place this system acts unattended.
- **DWB-625** - the stock read path is deliberately excused in the allowlist, but its
  recorded reason says "inspected by a human" and nothing on that route can tell a human
  from an agent. Documentation correctness in the one place documentation is load-bearing.
- **DWB-618** - whether `identity.md` should carry a token ceiling at all, given it is
  scaffold-generated and no agent can edit it.

## The instrument worth keeping

`backend/scripts/suite_fingerprint.py`. Eleven checking instruments failed in one
evening, every one working exactly as written and answering a narrower question than the
claim built on it. This is the one that survived inspection - and it survived *the
inspections that were run on it*, which is a weaker claim and the right one. Promote it on
its properties:

- hashes file CONTENT per file. `git status --porcelain` emits `<XY> <path>` and carries
  no content, so it cannot move on a content-only change to an already-dirty file - the
  dominant shape when several lanes are live. That is a proof from the output format, not
  an experiment.
- derives its scope from what the SUITE READS, including the gitignored memory corpus that
  no git view can see.
- refuses PER ROOT on an empty scope, because a hash of nothing is perfectly stable.
- states the ROLE beside every number: content hashes answer *did it change*, byte and file
  counts answer *did it have input* and are not change detectors. A number whose role is
  unstated gets promoted to evidence by the next reader.

**A number without its tree is not a number.** The endpoint still reports a stale figure;
post one only with its commit and the uncommitted work named beside it.

## What this session actually taught

Nobody caught their own scope error. Not one, all evening. Every correction came from
someone reading a result without having run the check - and the person who ran it is
structurally the worst placed to ask, because they chose the scope.

That is a property of the arrangement rather than of anyone's diligence. It survives
tiredness and it does not survive working alone. The lead's job is to put the two people
either side of a seam in direct contact, not to review both halves personally - reviewing
both halves means reading both from the same angle twice.
