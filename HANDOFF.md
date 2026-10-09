# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-10-09)

HEAD `c298217` on master, five commits today, tree clean.
Reinforcement works and runs in production on DWB. IND is switched off.

## What shipped

**Reinforcement fired for the first time since it was built.** DWB-644: the
match relation was inverted. The needle was the user's whole prompt and the
haystack was the lesson body, so a scar could only fire when someone recited
the lesson back - and could fire on an ordinary English phrase that happened
to sit inside a lesson. `fired_count` was 0 on all 877 rows. Now the needle is
the lesson's own keywords and the haystack is the situation; the body is never
searched. Eight rows have fired in production, all correct recalls.

**A keyword now has to be reachable from the moment it is written for.**
DWB-667: 288 scars were keyworded as filing labels (`self-exempt`,
`decompose-the-count`) rather than words anyone types. A write now carries an
author-written `situation`, and keywords must match it under the matcher's own
predicate, imported rather than copied. `POST /memories/{id}/rekey` replaces
keywords on an existing row, owner-only.

**Ordinary-word keywords are refused.** DWB-669: widening made recall work and
made junk worse. `before i` is two ordinary words, clears the two-token floor
by itself, and fires on any first-person sentence. A keyword is refused when it
clears the floor alone AND every token is a non-subject word. Both conditions
are required - the first alone would delete `git checkout` and `shared tree`.

## The numbers, with what they cover

Frozen 30 situations, written by the one agent not re-keywording, before anyone
started, seen by no author:

    recall any      4/30 -> 10 -> 19 -> 18 -> 17 -> 16
    recall correct  4/30 ->  8 -> 14 -> 14 -> 14 -> 14

**The correct number has not moved since pass two, through five corpus changes.
Every step down in the any-number was a junk or borderline route dying.**

Junk: the subjectless channel measures zero on 20 project-vocabulary controls.
Three fires remain, all carrying a subject word; one is a DB column matching a
UI column, which is a domain collision no word list reaches.

**What the number does not cover** (Pam): identical before/after proves the
drops cost no recall ON THAT SET. A term doing real work for a situation nobody
probed scores the same as a dead one, because both contribute zero to a set
that never asks. Same shape as the Bucket C question, unanswered.

## The evidence that is not self-measured

After the freeze lifted, nine memory rows were written by five independent
authors through both gates. ZERO carry a subjectless keyword, ZERO are below
the match floor, and nobody had to work around a refusal. Store-wide sweep on a
fresh connection afterwards: DWB 403 scars, zero offenders; IND one, the
unswept project. That is the first evidence in either ticket that is not an
instrument measuring itself.

## One correction worth inheriting

The subject rule was reported twice, in writing, as refusing `before and after`.
It did not - `after` had never been added to the list, and the function was
never called on the keyword. The store-wide sweep reported zero offenders while
that keyword sat live on IND. Fixed, and the account is in the module beside the
word. **A rule's test suite only contains the cases somebody thought to write
down**, so the tests passed either way.

`test_memory_recession_dwb623::test_several_agents_wrapping_up_concurrently_still_terminates`
is load-sensitive, not broken: it compares timestamps across a 1.5s gap against
MySQL second-rounding and fails when something else is hitting the same MySQL.
Passes alone and on a clean full run.

## The second half, shipped the same day

**CORE is consulted now.** It never was: promotion at three firings removed a
lesson from the only path that could recall it, permanently, because there was
no way back. A CORE row has since fired in production on DWB - #390, the lesson
about thirteen tickets meeting their criteria while the feature did not exist.
The two rows that were one fire from being silenced are now one fire from being
promoted and staying searchable. The reward stopped being the punishment.

`demote_from_core` exists, owner-only, reason required, journals the ruling
before moving the tier. `promote_to_core` no longer clears `context_key`.

**CORE was the untouched pre-667 corpus** - no re-keywording worksheet ever
included it, 2 of 126 reachable against 56 of 604 scars. All 86 DWB rows (mine)
are re-keyworded; the other 39 are IND's and 1 is an orphan probe, so DWB's CORE
is complete.

**A service edit on this box IS a deploy.** uvicorn runs `--reload`, so
`CONSULTED_TIERS` went live the moment it was saved, with no gate between an
edit and production. That is how #390 fired before anyone reported the change.

## Open, needing a decision

- **DWB-672: the subject rule is calibrated on general English** and this corpus
  is made of project nouns. `ticket`, `done`, `sprint`, `review` carry a subject
  everywhere except here. Junk climbed 0/20 to 1/20 on CORE through a bare-generic
  PAIR, which DWB-669 criterion 4 recorded as not-enforced on the defence "we saw
  none" - now falsified twice, in two corpora. The decision may still be right on
  cost; the defence is gone.
- **DWB-671: delete_agent 500s on journal entries**, and delete_project strands
  tiered rows with no clock origin. Four exist, all probe rows with journal copies.
- **IND is unswept and its reinforcement is OFF.** 195 scars, 310 keyworded
  rows, none touched by the rule. `before and after` is live there on
  Sylvie_IND #939. Turned off rather than left armed on a corpus nobody cleaned.
- **Bucket C, computed as a lower bound, not acted on.** Rows that kept the
  floor but lost their only route to their own situation. Four found inside the
  frozen 30, zero of them correct recalls; Stan's #517, #542 and #495 are real
  cases outside the set that the instrument structurally cannot see.
- **DWB-666, DWB-643, DWB-664** unchanged and still open. 664's fill route is
  incomplete and committed as in-flight.

## The lesson the whole team converged on

**A rule in your own memory is not a second person.** Four people broke the same
rule in the act of applying it - a plural changed to a singular, `trim` losing
`trimming`, a synonym added for the term being removed, a junk keyword written
in the session that named the class. None was careless. The first pass lost three
working recalls to it; the second replaced care with an assertion (import the
previous set, refuse any write that is not a strict superset) and lost nothing.

And the one that governs every number here: **a gate you satisfy with your own
sentence measures reachability, not recall, and the flattering number arrives
first.** Stan self-reported 6/9, rewrote the probes from the other end and got
4/18 on the same rows. Every self-measured rate in this work is flattered the
same way. The frozen set is the only instrument nobody could tune against.

## Team

Archie_DWB (13), Pam_DWB (14), Freddie (19), Barry_DWB (21), Sylvie (27),
Dolores (28), Stan (38), Devin_DWB (188, new). All participants wrote memory
this session. Roster is DB-authoritative: `GET /api/projects/1/team`.
