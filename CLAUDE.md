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

## MANDATORY: The PM Agent

**You MUST spawn a PM agent (@pm) on every team.** The PM is not optional. The PM:
- Creates sprints and tickets in the DWB API
- Monitors progress and updates ticket statuses
- Raises alerts when blockers are found
- Logs failure records when tickets need rework
- Closes sprints (with gate enforcement)
- Does sprint evaluations

**The PM's playbook is at `docs/pm_playbook.md`** — the PM must read it on startup.
**Your playbook is at `docs/team_lead_playbook.md`** — read it on startup.

## Team Structure

Every team needs at minimum:
- **@pm** (REQUIRED) — project manager, reads `docs/pm_playbook.md`
- **Team Lead (you)** — orchestrator, reads `docs/team_lead_playbook.md`

Then add workers based on the project:
- **@frontend-worker** — React, CSS, UI work
- **@backend-worker** — FastAPI, SQLAlchemy, Python
- **@system-ops** — Docker, scripts, infra, DevOps
- **@tester** — writes tests, runs suites, files bugs

Agent names in the DWB system should match Claude teammate names. The `role` field on agents maps to the Claude teammate name (e.g., role="frontend-worker" matches @frontend-worker).

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
6. Sprint close auto-creates: test ticket for next sprint, token scan, alerts to team

## Token Tracking

Tokens are tracked per ticket. Two methods:
- **Transcript scan**: `./scripts/run_token_scan.sh --project-id 1` reads Claude JSONL transcripts and attributes tokens to tickets
- **Manual POST**: `POST /api/tickets/:id/tokens {"tokens_used": N}`
- **Auto-alert**: if a ticket is closed with 0 tokens, an alert reminds the team

## Failure Analysis

When a ticket moves back to in_progress after being done (rework), the system:
1. Auto-creates a failure record stub
2. Alerts the PM to fill in the failure type
3. Blocks sprint close until the PM reviews it

Failure types: context_degradation, spec_drift, sycophantic_confirmation, tool_selection_error, cascading_failure, silent_failure, integration_failure

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
| List projects | GET /api/projects |
| Create agent | POST /api/agents |
| Assign agent to project | POST /api/project-agents |
| Create epic | POST /api/epics |
| Create sprint | POST /api/sprints |
| Create ticket | POST /api/tickets |
| Update ticket status | PATCH /api/tickets/:id |
| Post tokens | POST /api/tickets/:id/tokens |
| Post test results | POST /api/test-results |
| Check health | GET /api/status |
| Gate status | GET /api/projects/:id/gate-status |
| Activity feed | GET /api/projects/:id/activity-feed |
| Failure summary | GET /api/failure-records/summary |
| Token audit | GET /api/tokens/audit |
| Dismiss all alerts | POST /api/alerts/dismiss-all |
| Scan tokens | POST /api/projects/:id/scan-tokens |
| Deploy playbooks | POST /api/projects/:id/deploy-playbooks |

See README.md for the full 67-endpoint reference.
