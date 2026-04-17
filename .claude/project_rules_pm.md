# Project Rules — PM

> Project-specific rules for the PM on the DWB project. This file is NOT overwritten by deploy.

## DWB Agent Roster (Project 1)

| agent_id | Name   | Role             | Notes                     |
|----------|--------|------------------|---------------------------|
| 1        | Archie | team-lead        | TL — orchestrator         |
| 2        | Mona   | pm               | You — PM                  |
| 3        | Pixel  | frontend-worker  | React, CSS, components    |
| 4        | Devin  | backend-worker   | FastAPI, SQLAlchemy, Alembic |
| 5        | Bolt   | system-ops       | Docker, scripts, infra    |
| 6        | Sage   | tester           | pytest, vitest, bug filing|

Your agent_id is **2**. Always use `X-Agent-ID: 2` on mutating requests.

## Ticket Numbering

- Prefix: `DWB`
- Ticket keys: `DWB-NNN` (e.g., DWB-252)
- ticket_number is an incrementing integer per project — check the highest before creating
- ticket_key must be unique — the API enforces this

## Sprint Conventions

- Sprint numbers are sequential (currently at 47+)
- Sprint names auto-generate from the goal — write descriptive goals, not "Sprint N"
- One active sprint at a time per project
- Sprints auto-assign to the current epic
- Epic 17 ("Team Manifest, Playbooks & Gates") is the current epic

## Sprint Gates (7 total)

DWB enforces these gates on sprint close:
1. `force_test_run` — at least one test run during the sprint
2. `force_test_coverage` — every router has a test file
3. `force_initial_md` — INITIAL.md exists in repo
4. `force_architecture_md` — ARCHITECTURE.md exists in repo
5. `force_team_md` — TEAM.md exists in repo
6. `force_handoff_md` — HANDOFF.md exists in repo
7. `force_headers` — reserved/not yet enforced

Plus: unreviewed failure records (type=TBD) block close.

## Team Status (Ticket-Driven)

Team Status is driven by ticket status — no registration or hooks needed. An agent shows as "working" if they have an `in_progress` ticket. Move tickets to `in_progress` promptly when starting work, and out of `in_progress` when done. Stale tickets (in_progress for 10+ minutes) trigger automatic alerts.

## Alert Patterns

- **0-token done tickets** — info alert fires automatically. Usually means hooks aren't attributing. Investigate if persistent.
- **Sprint close** — auto-creates alerts for TL, PM, tester + test ticket for next sprint.
- **Doc gate failures** — critical alert for TL. Check that INITIAL.md, ARCHITECTURE.md, TEAM.md, HANDOFF.md all exist.
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
Currently showing 0 on most tickets — hooks not fully attributing. Flag this if it persists but don't block sprints on it.
