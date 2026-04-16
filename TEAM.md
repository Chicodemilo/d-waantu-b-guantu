# Team — D'Waantu B'Guantu

## Roster

> Archie and Pam are mandatory on every project. Add workers based on project needs.

### Mandatory

| Name | Duty | Playbook |
|------|------|----------|
| Archie | Team lead — plans sprints, assigns tickets, reviews work, orchestrates agents | `.claude/agents/team-lead.md` |
| Pam | Project manager — tracks tickets, monitors progress, sprint health, alerts | `.claude/agents/pm.md` |

### Workers

| Name | Duty | Playbook |
|------|------|----------|
| Devin | Backend — FastAPI, SQLAlchemy, Alembic migrations, Python services | `.claude/agents/backend-worker.md` |
| Pixel | Frontend — React, Vite, Zustand, plain CSS, component development | `.claude/agents/frontend-worker.md` |
| Bolt | System ops — Docker, scripts, env vars, infrastructure, DevOps | `.claude/agents/system-ops.md` |
| Sage | Tester — pytest, vitest, test coverage, test runner, bug filing | `.claude/agents/tester.md` |

> All workers also receive the general worker playbook: `.claude/agents/worker.md`

## Project Context

- **DWB Project ID:** 1
- **Prefix:** DWB
- **Repo:** /Users/mchick/Dev/d-waantu_b-guantu
- **Jira:** none

## Session Continuity

### Current State
Sprint 46 active — Team Manifest & Worker Playbook (epic 17). Adding force_team_md gate, worker.md playbook, and TEAM.md template.

### Active Decisions
- Passive hook-based token tracking (Sprint 43) — no manual token reporting
- Plain CSS only, terminal aesthetic
- PM is mandatory on every team
- Teams stay alive until user says to shut down
- MySQL DB name stays `local_agent_tracker` (legacy, not changing)

### Gotchas
- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for enum ALTER
- Frontend vitest has 23 pre-existing mock failures (`response.text is not a function`) — not blocking
- `deploy-playbooks` endpoint pushes agent playbooks to other project repos

### Last Session
Sprint 45 completed — FK cascade on ticket child tables, `cancelled` enum value, datetime.utcnow() deprecation fix, TL+PM playbook updates for passive tracking. 413 backend tests passing.
