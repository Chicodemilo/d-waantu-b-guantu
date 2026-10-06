# Project Rules — Team Lead

> Project-specific rules for the TL. This file is NOT overwritten by deploy.
> Last verified against the API: 2026-10-06.

## DWB Project Context

- **Project ID:** 1, **Prefix:** DWB, **Repo:** `/Users/mchick/Dev/d-waantu_b-guantu`
- **DB name:** `local_agent_tracker` (legacy, don't change)
- **No Jira** on this project — `jira_base_url` is null, so ticket writes refuse `jira_issue_key`. Never invoke `dwb2jira` here.
- **`memory_mode` is `human_memory`**, and DWB is the only project running it. Stock memory is sealed: `memory/append`, `session-complete`, `memory/compact` and `memory/condense` all return 409 here. Lessons go to `POST /api/agents/{id}/memories`, episodes to `POST /api/journal`. This applies to you too.
- **`runs_own_tests` is true** — DWB runs its own suite rather than the generic runner.
- Current counters (verify, don't trust): sprints 83 (max id 177), tickets 623 (max key DWB-636, max id 1631), epics 26 (max id 68).

## TL Behavioral Rules

- **Never write code or edit files directly.** Delegate ALL implementation to workers, then review. Exceptions: `HANDOFF.md`/`ARCHITECTURE.md`/`README.md`, `.claude/*` (only the TL can edit those safely), and the user-signalled small-change path in the playbook § 4c.
- **Never shut down teams** unless the user explicitly asks. Sprint close and idle teammates are not shutdown signals.
- **Always re-deploy playbooks** to active projects after committing changes to `docs/`. Deploy copies current state — commit without deploy leaves other projects stale.
- **Ticket display (non-Jira):** `| DWB # | Sprint | Title | Owner | Status |`. One row per ticket, `—` for empty, current project only. The 8-column Jira layout in `.claude/pm_playbook.md § Ticket Display Format` does NOT apply here.
- **Pam handles status updates and registrations** when spawned. With <3 parallel workers there is no PM and the TL files directly.

## Team Composition (DWB)

Roster is DB-authoritative — `GET /api/projects/1/team`. As of 2026-10-06:

- Archie_DWB (id=13) — team-lead
- Pam_DWB (id=14) — pm
- Barry_DWB (id=21) — backend-worker
- Stan (id=38) — backend-worker
- Freddie (id=19) — frontend-worker
- Sylvie (id=27) — system-ops
- Dolores (id=28) — docs-writer

No tester is on the roster. Spawn one as Sage_DWB if a sprint needs it; the old rules file listed Sage as current, which was wrong.

CC teams do not survive a session — a roster row is registration, not a live process.

## Architecture — Two Playbook Layers

1. **`docs/` = deployable playbooks** — generic, pushed to other projects via deploy-playbooks. Overwritten on every deploy.
2. **`.claude/agents/` = local agent defs** — Claude Code teammates in THIS repo only. Not deployed.
3. **`.claude/project_rules_*.md` = project-specific rules** — created blank on deploy, never overwritten. Each agent reads theirs on startup.

## Sprint Conventions

- One active sprint, one in-progress epic — DB-enforced, a second returns 409.
- Sprint names descriptive (from goal), not "Sprint N".
- **Gates enabled (per `/api/projects/1/gate-status`):** `force_initial_md`, `force_architecture_md`, `force_handoff_md`, `force_test_run`, `force_test_coverage`. OFF: `force_coding_standards_md`, `force_standards_audit`, `force_consolidation`, `force_headers`. `force_team_md` was removed in DWB-321 (roster is DB-authoritative).
- Always-on close gates independent of toggles: write-on-close memory (DWB-519) and the failure-record review.

## Key Patterns Learned

- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for ALTER TYPE.
- Frontend vitest has pre-existing mock failures — known, not blocking.
- Team Status panel is ticket-status driven (deterministic) — no hooks or registration needed.
- Adding a new doc gate is 4-point wiring (model, schema, router `_DOC_GATES`, sprint close loop) + `_DOC_FILES` + seed demo.
- Behaviour rules have a second home in code generators (`agent_memory.py`, `config/memory_rules.py`) and go stale silently — grep those when a behaviour ticket lands.
- Run one-off DB scripts from `backend/` (cwd-relative `.env`), and restart uvicorn with `--reload` after a pull or it serves pre-pull code.
