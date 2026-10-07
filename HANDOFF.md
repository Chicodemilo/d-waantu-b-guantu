# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-10-07, pushed and green)

HEAD `4f45674` on master, 3019 passed, 0 failed. Five commits today. Working
tree clean. All five active projects deployed with mode-correct playbooks.

**Two projects run `human_memory`: IND (40) and DWB (1).** Not just IND. On both,
`memory/append`, `memory/condense`, `memory/compact` and `session-complete`
return 409; lessons go to `POST /api/agents/{id}/memories`, episodes to
`POST /api/journal`. A `/memories` row satisfies the write-on-close gate.

## What shipped

**IND's memory serves again.** 298 rows had no clock origin because an adoption
run executed entirely in the gap between two sessions. Backfilled: 293 at origin
2651, 5 at 2657. `spawn-prepare` for Archie_IND went 583 chars to 20253. Zero
NULL-origin rows on IND at any tier.

The origin is a FLOOR, not a birth certificate. No row stamped 2651 was created
during 2651; it is the last tick before the rows existed, which is correct for a
consumer comparing strictly greater-than and false as provenance. Use `created_at`
and `memory_transitions` for real provenance.

**A memory can no longer be written without a session.** One module, one rule,
every writer. Caller-facing writes refuse with 400; the background consolidation
pass defers. The ticket named two writers; there were three.

**DWB was the thing teaching the sealed routes.** The rules block pasted into
every spawn bundle, `identity.md`, and eleven sites across four playbooks all
told agents to call routes that 409.

**The wrong memory mode's sections are now stripped at deploy**, by the mechanism
that already strips jira blocks. Unmarked content is shared — a decision, because
every existing line is unmarked.

## Open, needing Miles

- **DWB-644: reinforcement has never run in production.** `fired_count` 0 and
  `last_reinforced_session_id` NULL on all 779 rows. The match relation is
  backwards: a scar fires only when the user's whole prompt is a verbatim
  substring of the lesson, i.e. when they are reciting it back. It also fires on
  coincidence — `that is the` matches 8 scars — and three coincidental prompts
  promote into CORE, which never decays. **Do not flip `topoff_enabled` as the
  fix; the flag is the only thing keeping it latent.**
- **DWB-643: `gate-status` reports `all_passing` while never evaluating three
  gates sprint close enforces**, two of which are enabled here. The green light
  on the project page is lying.
- **DWB-640: stick redemption is unreachable** on human_memory. The redeem chain
  only runs after a stock append.
- **DWB-641: NOT NULL on `created_session_id`** is blocked on a design question —
  `project.py`'s delete path nulls it deliberately so global agents do not lose
  lessons when an unrelated project goes.
- **DWB-642:** a raw row with no origin is indistinguishable from a normal fresh
  one; `reason` reports `untiered` for both.
- **DWB-646** (spec says "Not built" while eight files cite it) and **DWB-647**
  (project_rules sends workers to `dwb2jira` on a project with no Jira). 647 is
  the TL's — workers crash writing under `.claude/`.
- **DWB-639** is a standing audit lane. `docs/doc_audit_backlog.md`, 11 items,
  each verified against a running system.

## The lesson worth carrying

Four times today a number was true when read and false when sent, in a tree
several people were writing at once — a line citation, a row count, a marker
census, a suite result. No amount of re-checking fixes that; two careful reads
give two correct-then-stale values. Cite symbols, not line numbers, and state
the predicate beside every count.

And the sharper one, from the doc side: correctness of every sentence does not
imply correctness of the document, because the defect can be which sentences are
PRESENT. Three deployed files carried the wrong mode's content after every line
had been checked against the code. Review the output of a pipeline, never its
input.

## Team

Shut down at Miles's request. Roster is DB-authoritative:
`GET /api/projects/1/team`. Archie_DWB (13), Pam_DWB (14), Barry_DWB (21),
Dolores (28), Stan (38) all participated and all have memory writes on record.
CC teams do not survive a session; respawn via the full flow in
`docs/team_lead_playbook.md` § 4a.
