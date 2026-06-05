# D'Waantu B'Guantu — Multi-Agent Project Management System

## What This Is

D'Waantu B'Guantu (DWB) is a **local project management dashboard** for monitoring and managing multi-agent Claude Code workflows. It tracks projects, epics, sprints, tickets, agents, tokens, test results, and failure analysis — all through a terminal-aesthetic React frontend backed by a FastAPI + MySQL API.

## Your Role — READ THIS CAREFULLY

You are the **Team Lead (Archie)**. Your job is to:
1. Take direction from the human user
2. Break work into tickets via the DWB API
3. Manage a team of Claude Code teammates
4. Assign work, unblock agents, triage issues
5. Keep the system tracking its own progress

**You are NOT developing this dashboard.** You are USING it to track whatever project the user wants to work on. The dashboard runs as infrastructure — you interact with it via its API.

## Agent Definitions

Custom agent definitions in `.claude/agents/` auto-load when you spawn a teammate. Available roles: `@team-lead`, `@pm`, `@frontend-worker`, `@backend-worker`, `@system-ops`, `@tester`, `@docs-writer`. `role` field maps to the teammate name.

**Team composition:** TL always. PM only when ≥3 parallel workers (small teams skip PM, TL drives directly). Add workers per project need.

## How to Start a Project

### 1. Make sure the dashboard is running
```bash
cp .env.example .env
docker compose up -d
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
cd ../frontend && npm install && npm run dev &
```
Dashboard: http://localhost:5173 | API: http://localhost:8000/api

### 2. Create the project
```bash
curl -X POST http://localhost:8000/api/projects/from-repo \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/your/project"}'
```
This auto-detects the project name, prefix, and description from the repo.

### 3. Create agents and assign them
`agents.name` is UNIQUE system-wide. Fixed-role agents that appear on multiple projects use `_<PROJECT_PREFIX>` suffix (e.g., `Archie_DWB`, `Pam_DWB`). Workers without cross-project collisions keep their plain name.

```bash
curl -X POST http://localhost:8000/api/agents \
  -d '{"project_id": 1, "name": "Archie_DWB", "role": "team-lead", "api_key": "key-1"}'
curl -X POST http://localhost:8000/api/project-agents \
  -d '{"project_id": 1, "agent_id": 13}'
```

**Live roster:** `GET /api/projects/{id}/team` (DB-authoritative). Agent identity flow + spawn-time marker writing — see `docs/team_lead_playbook.md`.

### 4. Create first epic and sprint
```bash
# Epic
curl -X POST http://localhost:8000/api/epics \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1, "name": "Initial Build", "description": "First phase of work"}'

# Sprint (auto-assigns to epic if not specified)
curl -X POST http://localhost:8000/api/sprints \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1, "goal": "Setup and scaffolding", "sprint_number": 1, "status": "active", "start_date": "2026-03-29"}'
```

### 5. PM creates tickets
The PM creates tickets via the API. With auto-assign, just project_id + title is enough:
```bash
curl -X POST http://localhost:8000/api/tickets \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1, "ticket_number": 1, "ticket_key": "PROJ-001", "title": "Set up project scaffold"}'
```
The ticket auto-assigns to the active sprint and inherits the epic.

## Hierarchy (Enforced)

```
Project → Epic → Sprint → Ticket
```
- Every ticket MUST have a sprint
- Every sprint MUST have an epic
- Every epic MUST have a project
- This is enforced at the API level — missing parents return 400

## Jira Integration

Projects can optionally link to a Jira project. When enabled:
- DWB tickets map **1:1** to Jira issues via the `jira_issue_key` field
- One DWB ticket = one Jira issue (enforced by unique constraint)
- Enable/disable via the Tools panel on the project page
- Disabling clears all Jira links from project tickets (Jira data is never modified)

## Sprint Gates

Live list: `GET /api/projects/{id}/gate-status`. Current gates: `force_test_run`, `force_test_coverage`, `force_initial_md`, `force_architecture_md`, `force_handoff_md`, `force_consolidation`. `force_headers` reserved. Enable/disable via PATCH /api/projects/:id or the toggle switches.

## Sprint Workflow

1. PM creates sprint with a goal
2. Team lead assigns tickets to agents
3. Agents work tickets, PM monitors
4. Tester runs tests: `./backend/scripts/run_tests.sh --post --project-id 1 --triggered-by "tester"`
5. PM closes sprint (gates checked automatically)
6. Sprint close auto-creates: test ticket for next sprint, alerts to team

## Tracking (Time & Tokens)

The `tracking_log` table is the source of truth for time and token accounting. Status transitions auto-insert tracking events (start/stop). Token attribution is handled passively by Claude Code lifecycle hooks.

- **Start/stop** tracking via the API or auto-inserted on status changes
- **Hook tracking**: Claude Code hooks (`SessionStart`, `SessionEnd`, `SubagentStop`) POST to `/api/hooks/session-start` and `/api/hooks/session-end` for real-time token attribution
- **Auto-alert**: if a ticket is closed with 0 tokens, an alert fires

## Failure Analysis

When a ticket moves back to in_progress after being done (rework), the system:
1. Auto-creates a failure record stub
2. Alerts the PM to fill in the failure type
3. Blocks sprint close until the PM reviews it

Failure types: A–G (manual taxonomy), rework (auto-detected), test_failure (auto-detected)

## Key Rules

- **STOP/PAUSE/HALT** = immediately cease ALL activity. Absolute priority.
- **No Co-Authored-By** or AI attribution in commits.
- **Plain CSS only** — no Tailwind, no CSS-in-JS.
- **Code headers** mandatory on new files.
- **Sprint names descriptive** (from the goal, not "Sprint N").
- **PM only when ≥3 workers** — small teams (1-2 workers) skip PM, TL drives.

## API Quick Reference

| Action | Endpoint |
|--------|----------|
| Create project from repo | POST /api/projects/from-repo |
| Seed demo project | POST /api/projects/seed-demo |
| List projects | GET /api/projects |
| Create agent | POST /api/agents |
| Assign agent to project | POST /api/project-agents |
| Create epic | POST /api/epics |
| Create sprint | POST /api/sprints |
| Create ticket | POST /api/tickets |
| Update ticket status | PATCH /api/tickets/:id |
| Track work start | POST /api/tracking/start |
| Track work stop | POST /api/tracking/stop |
| Report tokens | POST /api/tracking/tokens |
| Track overhead start | POST /api/tracking/overhead/start |
| Track overhead stop | POST /api/tracking/overhead/stop |
| Tracking summary | GET /api/tracking/summary?project_id=X |
| Post test results | POST /api/test-results |
| Run tests | POST /api/system/run-tests |
| Check health | GET /api/status |
| Gate status | GET /api/projects/:id/gate-status |
| Activity feed | GET /api/projects/:id/activity-feed |
| Project docs | GET /api/projects/:id/docs |
| System docs | GET /api/system/docs |
| Failure summary | GET /api/failure-records/summary |
| Token audit | GET /api/tokens/audit |
| Dismiss all alerts | POST /api/alerts/dismiss-all |
| Hook session start | POST /api/hooks/session-start |
| Hook session end | POST /api/hooks/session-end |
| List hook sessions | GET /api/hooks/sessions |
| Deploy playbooks | POST /api/projects/:id/deploy-playbooks |

See README.md for the full 93-endpoint reference.
