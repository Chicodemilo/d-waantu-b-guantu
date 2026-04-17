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

This repo includes custom agent definitions in `.claude/agents/`. When you spawn a teammate, use the agent name and their full playbook — including all instructions, API references, and rules — auto-loads. **No manual "read this file" needed.**

| Spawn as | Definition file | Role |
|----------|----------------|------|
| `@team-lead` | `.claude/agents/team-lead.md` | Orchestrator — spawns teams, plans sprints, assigns work |
| `@pm` | `.claude/agents/pm.md` | Project manager — monitors progress, manages tickets, logs failures |
| `@frontend-worker` | `.claude/agents/frontend-worker.md` | React, Vite, Zustand, plain CSS, component development |
| `@backend-worker` | `.claude/agents/backend-worker.md` | FastAPI, SQLAlchemy 2.0, Alembic migrations, Python services |
| `@system-ops` | `.claude/agents/system-ops.md` | Docker, scripts, env vars, infrastructure, DevOps |
| `@tester` | `.claude/agents/tester.md` | pytest, vitest, test coverage, test runner, bug filing |

**The PM is MANDATORY on every team.** The PM creates sprints and tickets, monitors progress, raises alerts, logs failure records, closes sprints (with gate enforcement), and runs sprint evaluations. Never run a team without `@pm`.

Every team needs at minimum:
- **@team-lead** (you) — orchestrator
- **@pm** (REQUIRED) — project manager

Then add workers based on the project: `@frontend-worker`, `@backend-worker`, `@system-ops`, `@tester`.

Agent names in the DWB system match Claude Code teammate names. The `role` field on agents maps to the teammate name (e.g., `role="backend-worker"` matches `@backend-worker`).

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
```bash
# Create agents matching your Claude teammates
curl -X POST http://localhost:8000/api/agents \
  -H "Content-Type: application/json" \
  -d '{"name": "Archie", "role": "team-lead", "description": "Team lead", "api_key": "key-1"}'

# Assign to project
curl -X POST http://localhost:8000/api/project-agents \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1, "agent_id": 1}'
```

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

Projects can have validation gates that block sprint closure:
- **force_test_run** — a test run must be posted during the sprint
- **force_test_coverage** — all API routers must have corresponding test files
- **force_initial_md** — INITIAL.md must exist in the repo
- **force_architecture_md** — ARCHITECTURE.md must exist in the repo
- **force_headers** — (not yet enforced)

Enable via PATCH /api/projects/:id or the toggle switches on the project page.

## Sprint Workflow

1. PM creates sprint with a goal
2. Team lead assigns tickets to agents
3. Agents work tickets, PM monitors
4. Tester runs tests: `./scripts/run_tests.sh --post --project-id 1 --triggered-by "tester"`
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

- **STOP/PAUSE/HALT** from the user = immediately cease ALL activity. No tool calls, no messages, nothing. Absolute priority.
- **No Co-Authored-By** or AI attribution in git commits
- **Plain CSS only** — no Tailwind, no CSS-in-JS, styles in .css files
- **Code headers mandatory** on all files (see instructions page for format)
- **Sprint names must be descriptive** — "Token Tracking Hooks" not "Sprint 2"
- **PM is mandatory** — never run a team without a PM agent

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
