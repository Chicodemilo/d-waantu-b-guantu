# Project Rules — Team Lead

> Project-specific rules for the TL. This file is NOT overwritten by deploy.

## DWB Project Context

- **Project ID:** 1, **Prefix:** DWB, **Repo:** /Users/mchick/Dev/d-waantu_b-guantu
- **DB name:** `local_agent_tracker` (legacy, don't change)
- **No Jira** on this project — DWB only

## TL Behavioral Rules

- **Never write code or edit files directly.** Delegate ALL implementation to workers. Review their output. The only files you touch are HANDOFF.md and documentation content. (TEAM.md is deprecated — roster is DB-authoritative via `/api/projects/{id}/team`.)
- **Never shut down teams** unless the user explicitly asks. Sprint close and idle teammates are not signals to shut down.
- **Always re-deploy playbooks** to active projects after committing changes to `docs/`. The deploy copies the current state — if you commit then forget to deploy, other projects have stale playbooks.
- **Always present tickets in the 8-column table format** (DWB Ticket, Jira Ticket, DWB Sprint, Jira Epic, Jira Sprint, Title, Proposed Status, Current Status). This is in the TL playbook.
- **Pam (PM) handles status updates and registrations.** Don't do ticket housekeeping yourself.

## Team Composition (DWB)

Standard DWB team:
- Archie (id=1) — TL
- Mona (id=2) — PM
- Pixel (id=3) — frontend-worker
- Devin (id=4) — backend-worker
- Bolt (id=5) — system-ops
- Sage (id=6) — tester

## Architecture — Two Playbook Layers

1. **`docs/` = deployable playbooks** — generic, pushed to other projects via deploy-playbooks. Overwritten on every deploy.
2. **`.claude/agents/` = local agent defs** — for Claude Code teammates in THIS repo only. Not deployed anywhere.
3. **`.claude/project_rules_*.md` = project-specific rules** — created blank on deploy, never overwritten. Each agent reads theirs on startup.

## Sprint Conventions

- One active sprint at a time
- Sprint names are descriptive (from goal), not "Sprint N"
- Latest sprint: 47, latest ticket: DWB-252, latest epic: 17
- Gates: 7 enabled (force_headers, force_test_coverage, force_test_run, force_initial_md, force_architecture_md, force_handoff_md + failure records). `force_team_md` was removed in DWB-321 — roster is DB-authoritative.

## Key Patterns Learned

- Alembic autogenerate can't detect MySQL enum changes — always write manual migrations for ALTER TYPE
- Frontend vitest has 23 pre-existing mock failures — not blocking, known issue
- Team Status panel is ticket-status driven (deterministic) — no hooks or registration needed
- When adding a new doc gate: 4-point wiring (model, schema, router _DOC_GATES, sprint.py close loop) + _DOC_FILES + seed demo
