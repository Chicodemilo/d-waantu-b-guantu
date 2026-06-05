# Project Rules — PM

> Project-specific rules for the PM on the DWB project. This file is NOT overwritten by deploy.

## DWB Agent Roster

Live roster: `GET /api/projects/1/team`. DB-authoritative; do not hard-code names or IDs in this file. Your `agent_id` is **14** (Pam_DWB). Use `X-Agent-ID: 14` on every mutation.

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
- `force_test_run`, `force_test_coverage`, `force_initial_md`, `force_architecture_md`, `force_handoff_md`, `force_consolidation` (DWB-322).
- `force_headers` reserved/not yet enforced.
- `force_team_md` removed in DWB-321 (DB-authoritative roster).

Plus: unreviewed failure records (type=TBD) block close.

## Alert Patterns

- **0-token done tickets** — info alert fires automatically. Usually means hooks aren't attributing. Investigate if persistent.
- **Sprint close** — auto-creates alerts for TL, PM, tester + test ticket for next sprint.
- **Doc gate failures** — critical alert for TL. Check that INITIAL.md, ARCHITECTURE.md, HANDOFF.md all exist. (TEAM.md is deprecated — roster lives in DB.)
- **Rework detected** — info alert for PM when ticket goes back to in_progress after done. Auto-creates failure record stub.

## Common Workflows

### Moving blocked tickets
When a blocker finishes, immediately move the dependent ticket to `in_progress` and post a comment noting which blocker cleared. Don't wait for TL to ask.

### Sprint close checklist
1. All tickets done (or moved to next sprint)
2. `GET /api/projects/1/gate-status` — all_passing=true
3. `GET /api/failure-records?sprint_id=X&resolved=false` — no TBD stubs
4. `PATCH /api/sprints/X {"status": "completed"}`
5. Post sprint evaluation to activity log
6. Report to TL with scorecard

### Token attribution
Hook-driven (DWB-304/307). If a done ticket shows 0 tokens, check the agent's session marker resolved correctly (`GET /api/hooks/sessions?status=orphan`).
