# Project Rules — PM

> Project-specific rules for the PM on the DWB project. This file is NOT overwritten by deploy.

## DWB Agent Roster

Live roster: `GET /api/projects/5/team`. DB-authoritative; do not hard-code names or IDs in this file. Confirm your `agent_id` via `POST /api/agents/identify` at spawn (currently **12**, Pam_DWB) and use it in `X-Agent-ID` on every mutation.

## Hard Limits — Jira Sprint Authority (DWB-323)

PM has **NO authority** over Jira sprints (close/create/edit/delete). Pull/read only. **NEVER run `dwb2jira sprint close`** — Jira sprints span many users and closing one breaks every other assignee. Only DWB sprints are PM-owned. Tickets the user is not the Jira assignee of are also read-only. If TL asks for a Jira sprint op, REFUSE and escalate to the human. Code guard lands in DWB-324.

## Ticket Numbering

- Prefix: `DWB`
- Ticket keys: `DWB-NNN` (e.g., DWB-252)
- ticket_number is an incrementing integer per project — check the highest before creating
- ticket_key must be unique — the API enforces this

## Sprint Conventions

- Sprint numbers sequential (live count: `GET /api/sprints?project_id=1`).
- Sprint names auto-generate from the goal — write descriptive goals, not "Sprint N".
- One active sprint at a time per project.
- Sprints auto-assign to the current epic (live: `GET /api/epics?project_id=1&status=open`).

## Sprint Gates

Authoritative list: `GET /api/projects/1/gate-status`. Currently enabled on DWB:
- `force_test_run`, `force_test_coverage`, `force_initial_md`, `force_architecture_md`, `force_handoff_md` (DWB-322, DWB-004).
- OFF on DWB: `force_coding_standards_md`, `force_consolidation`, `force_standards_audit`, `force_headers`. Verified against the project row 2026-10-28; this list drifts, so trust gate-status over it.
- `force_team_md` removed in DWB-321 (DB-authoritative roster).

Plus: unreviewed failure records block close, and there are TWO kinds (`sprint.py`,
the unreviewed-failure-records gate). `failure_type == "TBD"` blocks on its own.
`failure_type == "rework"` blocks while `reviewed` is false — that is the
auto-detected stub, and it is the one that catches people, because a three-week-old
rework nobody looked at still blocks today's close.

## Alert Patterns

- **0-token done tickets** — no alert fires; this has never raised one. Closing with zero attributed tokens applies a score penalty only (`scoring_triggers.py`). **It does NOT usually mean hooks are failing** - that was the old guidance here and it sent people hunting the wrong thing. A session's tokens land on ONE ticket, so every other ticket the same worker closes in that session reads zero while carrying real tracked time. Measured 2026-10-28: 442 docks since June across 26 agents, 354 of them on tickets WITH tracked time. DWB-708. Miles has ruled the existing docks STAND and the work is prevention - do not re-escalate them.
- **Sprint close** — mints a test ticket onto the closing sprint as backlog, unassigned (DWB-566). No alerts fire; the per-role "tests needed" alerts were removed in DWB-463.
- **Doc gate failures** — critical alert for TL. Check that INITIAL.md, ARCHITECTURE.md, HANDOFF.md all exist. (TEAM.md is deprecated — roster lives in DB.)
- **Rework detected** — info alert for PM when ticket goes back to in_progress after done. Auto-creates failure record stub.

## Common Workflows

### Moving blocked tickets
When a blocker finishes, immediately move the dependent ticket to `in_progress` and post a comment noting which blocker cleared. Don't wait for TL to ask.

### Sprint close checklist
1. All tickets done (or moved to next sprint)
2. `GET /api/projects/1/gate-status` — all_passing=true
3. `GET /api/failure-records?sprint_id=X` — then filter CLIENT-SIDE for
   `failure_type == "TBD"`, or `failure_type == "rework" and reviewed is false`.
   `resolved` and `reviewed` are different columns and the gate reads `reviewed`;
   the list endpoint has no `reviewed` filter (DWB-510 added the column for the
   gate and never added the query param), so `resolved=false` answers a question
   nobody is asking and quietly returns the wrong set.
4. `PATCH /api/sprints/X {"status": "completed"}`
5. Post sprint evaluation to activity log
6. Report to TL with scorecard

### Token attribution
Hook-driven (DWB-304/307). **If a done ticket shows 0 tokens, do NOT start with `GET /api/hooks/sessions?status=orphan`.** Hook attribution was checked on 2026-10-28 and is not broken: 6035 hook sessions with no unclaimed markers. Check first whether the same worker closed another ticket in the same session - that is where the tokens went. An orphan hunt on these finds nothing, on all 442 of them.
