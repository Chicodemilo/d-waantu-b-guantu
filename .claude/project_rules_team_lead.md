# Project Rules — Team Lead

> Project-specific rules for the TL. This file is NOT overwritten by deploy.
> Last verified against the API: 2026-09-17.

## DWB Project Context

- **Project ID:** 5, **Prefix:** DWB, **Repo:** `/Users/mileschick/Dev/d-waantu-b-guantu`
- **DB name:** `local_agent_tracker` (legacy, don't change)
- **No Jira** on this project — `jira_base_url` is null, so ticket writes refuse `jira_issue_key`. Never invoke `dwb2jira` here.
- Current counters (verify, don't trust): sprints 4 (max id 25), tickets 36, epics 6 + 10.

## TL Behavioral Rules

- **Never write code or edit files directly.** Delegate ALL implementation to workers, then review. Exceptions: `HANDOFF.md`/`ARCHITECTURE.md`/`README.md`, `.claude/*` (only the TL can edit those safely), and the user-signalled small-change path in the playbook § 4c.
- **Never shut down teams** unless the user explicitly asks. Sprint close and idle teammates are not shutdown signals.
- **Always re-deploy playbooks** to active projects after committing changes to `docs/`. Deploy copies current state — commit without deploy leaves other projects stale.
- **Ticket display (non-Jira):** `| DWB # | Sprint | Title | Owner | Status |`. One row per ticket, `—` for empty, current project only. The 8-column Jira layout in `.claude/pm_playbook.md § Ticket Display Format` does NOT apply here.
- **Pam handles status updates and registrations** when spawned. With <3 parallel workers there is no PM and the TL files directly.

## Team Composition (DWB)

Roster is DB-authoritative — `GET /api/projects/5/team`. As of 2026-09-17:

- Archie_DWB (id=11) — team-lead
- Pam_DWB (id=12) — pm
- Barry_DWB (id=13) — backend-worker
- Freddie_DWB (id=14) — frontend-worker
- Sylvie_DWB (id=15) — system-ops
- Sage_DWB (id=16) — tester
- Dolores_DWB (id=17) — docs-writer

CC teams do not survive a session — a roster row is registration, not a live process.

## Architecture — Two Playbook Layers

1. **`docs/` = deployable playbooks** — generic, pushed to other projects via deploy-playbooks. Overwritten on every deploy.
2. **`.claude/agents/` = local agent defs** — Claude Code teammates in THIS repo only. Not deployed.
3. **`.claude/project_rules_*.md` = project-specific rules** — created blank on deploy, never overwritten. Each agent reads theirs on startup.

## Sprint Conventions

- One active sprint, one in-progress epic — DB-enforced, a second returns 409.
- Sprint names descriptive (from goal), not "Sprint N".
- **Gates enabled (per `/api/projects/5/gate-status`):** `force_initial_md`, `force_architecture_md`, `force_handoff_md`, `force_coding_standards_md`, `force_standards_audit`. OFF: `force_headers`. `force_team_md` was removed in DWB-321 (roster is DB-authoritative).
- Always-on close gates independent of toggles: write-on-close memory (DWB-519) and the failure-record review.

## Key Patterns Learned

- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for ALTER TYPE.
- Frontend vitest has pre-existing mock failures — known, not blocking.
- Team Status panel is ticket-status driven (deterministic) — no hooks or registration needed.
- Adding a new doc gate is 4-point wiring (model, schema, router `_DOC_GATES`, sprint close loop) + `_DOC_FILES` + seed demo.
- Behaviour rules have a second home in code generators (`agent_memory.py`, `config/memory_rules.py`) and go stale silently — grep those when a behaviour ticket lands.
- Run one-off DB scripts from `backend/` (cwd-relative `.env`), and restart uvicorn with `--reload` after a pull or it serves pre-pull code.
