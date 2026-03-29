# D'Waantu B'Guantu (DWB)

A multi-agent workflow dashboard for tracking Claude Code teammate progress, managing team instructions, enforcing sprint gates, and accounting for token spend. Built to coordinate autonomous AI agents working as a software team — with a team lead, PM, frontend worker, backend worker, system ops, and tester — each running as a Claude Code teammate.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Core Concepts](#core-concepts)
- [Agents and Roles](#agents-and-roles)
- [Instructions System](#instructions-system)
- [Testing](#testing)
- [Playbooks](#playbooks)
- [Token Tracking](#token-tracking)
- [Sprint Gates](#sprint-gates)
- [Adding a Project](#adding-a-project)
- [Status History and Time Tracking](#status-history-and-time-tracking)
- [Failure Analysis](#failure-analysis)
- [API Reference](#api-reference)
- [Configuration](#configuration)

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose (for MySQL)

### 1. Start the database

```bash
cp .env.example .env   # edit credentials if needed
docker compose up -d
```

This starts MySQL 8.0 on port `23847` (configurable via `MYSQL_PORT`) and phpMyAdmin on port `8080`.

### 2. Seed the database

```bash
mysql -h 127.0.0.1 -P 23847 -u lat_user -plat_dev_password local_agent_tracker < seed.sql
```

This loads sample projects (DWB, INGEST, RECON, DOCS), 13 agents, epics, sprints, tickets, instructions, and activity data.

### 3. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API is now at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard is now at `http://localhost:5173`.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│   React UI  │────▶│  FastAPI API  │────▶│  MySQL 8  │
│  Vite/5173  │◀────│   :8000      │◀────│  :23847   │
└─────────────┘     └──────────────┘     └───────────┘
                           │
                    ┌──────┴──────┐
                    │  Scripts &  │
                    │   Alembic   │
                    └─────────────┘
```

**Backend** — FastAPI with SQLAlchemy 2.0 ORM, Pydantic v2 schemas, three-layer architecture:
- `app/routers/` — HTTP endpoints, request/response handling
- `app/services/` — business logic, validation, automation triggers
- `app/models/` — SQLAlchemy table definitions
- `app/schemas/` — Pydantic request/response models

**Frontend** — React 18 with Vite, Zustand for state management, React Router for navigation. Vanilla CSS with a dark terminal aesthetic (JetBrains Mono, green/orange/blue on black). Adaptive polling refreshes data every 2s when sprints are active, 10s when idle.

**Database** — MySQL 8.0 via PyMySQL driver. Alembic manages schema migrations with autogenerate support. 13 tables including status_history and failure_records.

---

## Core Concepts

### Hierarchy

```
Project
  └── Epic
       └── Sprint
            └── Ticket
                 ├── StatusHistory (every status transition)
                 ├── Comment
                 └── FailureRecord (optional)
```

**Projects** have a unique prefix (e.g., `DWB`, `INGEST`) used to generate ticket keys. Each project tracks overhead tokens for the team lead and PM separately from ticket work. Projects have 5 sprint gate toggles and an optional `repo_path` for filesystem-level validation.

**Epics** group related work within a project. Statuses: `open` → `in_progress` → `completed`.

**Sprints** are time-boxed iterations under an epic. Statuses: `planned` → `active` → `completed`. Sprints have a `sprint_number`, optional `goal`, and optional `start_date`/`end_date`. When a goal is provided, the sprint name is auto-generated from it. Completing a sprint triggers gates validation, token attribution scan, alerts, and auto-test-ticket creation.

**Tickets** are individual work items within a sprint. Each has a `ticket_key` (e.g., `DWB-042`), a type (`task`, `bug`, `story`), and a status (`backlog` → `todo` → `in_progress` → `in_review` → `done`). Tickets track `tokens_used`, `time_spent_seconds` (auto-computed from status transitions), and `token_source` (transcript_scan, manual_estimate, unknown).

### Auto-assignment

Creating resources without specifying parent IDs triggers smart defaults:
- **Ticket without `sprint_id`** — assigned to the project's most recent active sprint
- **Ticket without `epic_id`** — inherits from the assigned sprint's epic
- **Sprint without `epic_id`** — assigned to the project's most recent open/in-progress epic

This keeps the API ergonomic for agents that shouldn't need to know the full hierarchy.

---

## Agents and Roles

Agents represent Claude Code teammates. Each has a human name and a `role` field that maps to their Claude Code teammate name (e.g., `backend-worker`, `team-lead`, `pm`).

| Agent | Role | Description |
|-------|------|-------------|
| Archie | team-lead | Claude Code team lead for DWB |
| Mona | pm | Project manager, sprint planning |
| Pixel | frontend-worker | React UI development |
| Devin | backend-worker | FastAPI/SQLAlchemy backend |
| Bolt | system-ops | Infrastructure, scripts, ops |
| Sage | tester | Test writing and validation |

Agents are assigned to projects via the `project_agents` join table. This controls which agents receive alerts when sprints close and enables dynamic role lookups — no hardcoded agent IDs in business logic.

Additional projects (INGEST, RECON, DOCS) have their own agents with different names but follow the same pattern.

---

## Instructions System

Instructions are rules that agents should follow. Three scopes:

| Scope | Target | Example |
|-------|--------|---------|
| `global` | All agents, all projects | "Use snake_case for Python, camelCase for JS" |
| `project` | All agents on a specific project | "DWB: plain CSS only, no frameworks" |
| `agent` | A specific agent | "Devin: SQLAlchemy 2.0 style, type hints required" |

Instructions are stored in the database and can be synced to/from Claude memory files:
- `GET /api/instructions/sync-check` — compares DB instructions with `.claude/` memory files
- `POST /api/instructions/sync` — creates DB records for memory-only instructions
- `scripts/sync_instructions.py` — CLI tool for bidirectional export/import to `docs/rules/`

---

## Testing

### Test suite

Tests live in `backend/tests/` using pytest. Each test runs in a transaction that rolls back after completion, using a separate `lat_test` database.

Fixtures in `conftest.py` provide factory functions: `make_project()`, `make_agent()`, `make_sprint()`, `make_ticket()`, etc. — each auto-creating parent entities as needed.

### Running tests

```bash
cd backend
source .venv/bin/activate
pytest tests/
```

Or with API reporting:

```bash
./scripts/run_tests.sh --post --project-id 1 --triggered-by "manual" --context "pre-release"
```

This runs pytest, generates a JSON report, and POSTs the results to `/api/test-results` with per-test details (nodeid, outcome, duration). Per-test durations are computed by summing setup + call + teardown phase durations from pytest-json-report.

### Test coverage tracking

`GET /api/status/test-coverage` scans `backend/app/routers/` and `backend/tests/` to report which routers have corresponding test files.

### Test performance tracking

`GET /api/test-results/performance` returns a lightweight projection of test run history: duration, pass/fail counts, suite, and status — used by the frontend for duration charts, sparklines, and performance trend analysis.

### Auto-failure records

When a test result is POSTed with `status="failed"`, the system auto-creates a `failure_record` for each failed test in the details JSON. Records are tagged with `failure_type="test_failure"` and attributed to the project's tester agent.

### Sprint gates

Projects can enforce testing requirements before sprints close. See [Sprint Gates](#sprint-gates).

---

## Playbooks

Playbooks are operational guides for the team lead and PM agents. They live in `docs/`:

- `team_lead_playbook.md` — how to create projects, manage sprints, assign agents, track tokens, onboard new projects
- `pm_playbook.md` — monitoring, sprint evaluation, alert raising, first-run checks

**Deploying playbooks** to a project's repo:

```
POST /api/projects/{id}/deploy-playbooks
```

This copies playbook files to `{project.repo_path}/.claude/` so Claude Code teammates can reference them.

`GET /api/playbooks` lists available playbook files.

---

## Token Tracking

Token usage is tracked at multiple levels with two attribution methods.

### Ticket-level tokens

Agents or the TL report tokens via:

```
POST /api/tickets/{id}/tokens
{"tokens_used": 15000, "time_spent_seconds": 120, "source": "manual_estimate"}
```

This increments (not replaces) the ticket's running totals and sets `token_source`.

### Transcript scanning

`scripts/attribute_tokens.py` scans Claude Code transcript files (`~/.claude/projects/`) and attributes tokens to tickets:
1. Finds JSONL transcripts matching the project
2. Reads `agentName` from each transcript to identify the agent
3. Counts tokens (input + cache_creation + cache_read + output)
4. Finds the agent's in_progress or todo ticket
5. POSTs tokens with `source="transcript_scan"`
6. Tracks attributed sessions in a state file to prevent double-counting

Trigger manually via API:

```
POST /api/projects/{id}/scan-tokens
```

Returns: `{sessions_found, sessions_attributed, total_tokens, attributions: [{agent, ticket_key, tokens}]}`

### Automatic scan on sprint close

When a sprint transitions to `completed`, the token attribution scan runs automatically. Failures are caught and logged as alerts — they never block sprint close.

### Stop hook (report_tokens.py)

`scripts/report_tokens.py` can run as a Claude Code stop hook for real-time token tracking. Reads hook event JSON from stdin, parses the transcript for token counts, and POSTs deltas to the API. Delta tracking via state file prevents double-counting from repeated `TeammateIdle` events.

### Token audit

`GET /api/tokens/audit` aggregates token usage across the system:
- Total ticket tokens
- Tokens by agent
- Tokens by project (ticket tokens + TL overhead + PM overhead)
- Discrepancy detection (e.g., unassigned ticket tokens)

### Token attribution detail

`GET /api/tickets/{id}/token-attribution` returns a breakdown for a single ticket:
- `ticket_key`, `tokens_used`, `time_spent_seconds`, `source`
- `history` array (reserved for future per-POST tracking)

### Auto-alerts

When a ticket is marked `done` with `tokens_used == 0`, an info alert is auto-created: "Tokens not reported for {ticket_key}".

---

## Sprint Gates

Projects have five boolean toggles that gate sprint completion:

| Toggle | What it checks |
|--------|---------------|
| `force_test_run` | At least one test run exists for the project since the sprint's start date |
| `force_test_coverage` | Every router file in `app/routers/` has a corresponding `test_*.py` file |
| `force_initial_md` | `INITIAL.md` exists at the repo root |
| `force_architecture_md` | `ARCHITECTURE.md` exists at the repo root |
| `force_headers` | Reserved for v2 (code header enforcement) |

Additionally, the system checks for **unreviewed failure records** on sprint tickets. If any `failure_record` has `failure_type="TBD"` or is an auto-detected rework stub (`failure_type="rework"` with "Auto-detected" in notes), the sprint cannot close until the PM reviews and updates them.

Enable via project update:

```
PATCH /api/projects/{id}
{"force_test_run": true, "force_test_coverage": true}
```

When a sprint is PATCHed to `completed`, the gates are checked **before** the status change is committed. If any gate fails, the API returns `400` with a descriptive error and the sprint stays in its current state.

### Documentation gate status

`GET /api/projects/{id}/gate-status` checks each doc gate and returns pass/fail status. If a gate is failing, it auto-creates a deduplicated critical alert for the TL agent.

### On successful sprint completion

When a sprint transitions to `completed`:
1. Info alerts are created for the team-lead, PM, and tester agents (looked up dynamically by role from `project_agents`)
2. If an active sprint exists for the same project and a tester agent is assigned, a test ticket is auto-created: "Write tests for S{N}: {sprint_name}"
3. Token attribution scan runs automatically (failures logged as warning alerts, never block close)

---

## Adding a Project

### From an existing repo (recommended)

```
POST /api/projects/from-repo
{"repo_path": "/path/to/repo"}
```

This scans the repo for metadata (`package.json`, `pyproject.toml`, `README.md`) and auto-populates:
- **prefix** — generated from the project name (max 6 uppercase chars, deduplicated against existing prefixes)
- **name** — cleaned and title-cased from the directory or package name
- **description** — pulled from package.json, pyproject.toml, or the first non-heading line of README.md

The endpoint also enables `force_initial_md` and `force_architecture_md` gates by default, and auto-checks doc gates to create alerts for any missing required files.

### Manual creation

```
POST /api/projects
{
  "prefix": "MYPRJ",
  "name": "My Project",
  "description": "What this project does",
  "repo_path": "/path/to/repo"
}
```

### Onboarding flow

After a project is created, the team lead should:

1. **Check documentation gates** — `GET /api/projects/{id}/gate-status` returns which gates are passing or failing. If `force_initial_md` or `force_architecture_md` are enabled, the gate fails until those files exist at the repo root. Missing docs auto-create critical alerts for the TL.

2. **Assign agents** — at minimum, assign a team-lead, PM, and one worker via `POST /api/project-agents`.

3. **Create an epic** — `POST /api/epics` for the first major milestone.

4. **Create a sprint** — `POST /api/sprints` with a goal. Set status to `active` when work begins.

5. **Write required docs** — create `INITIAL.md` (project origins, goals, constraints) and `ARCHITECTURE.md` (system design) at the repo root.

6. **Deploy playbooks** — `POST /api/projects/{id}/deploy-playbooks` copies operational guides to the repo's `.claude/` directory.

7. **Create tickets** — break work into tickets assigned to agents within the sprint.

The PM should independently verify onboarding by checking gate status, metadata completeness, and agent assignments (see the PM playbook).

---

## Status History and Time Tracking

### Status history

Every ticket status change is recorded in the `status_history` table with old_status, new_status, changed_at, and changed_by_agent_id. This provides a complete audit trail of ticket lifecycle transitions.

```
GET /api/tickets/{id}/history
```

Returns the full status history for a ticket, sorted chronologically.

### Automatic time computation

When a ticket's status changes, the system walks its full status_history and computes total time spent in `in_progress` — summing the duration between each `in_progress` entry and the next transition out. The computed value is written to `ticket.time_spent_seconds`. Open intervals (currently in_progress) are not counted until the next transition.

### Rework detection

When a ticket moves to `in_progress` and has a previous `done` entry in its status_history, the system auto-detects rework:
- Creates a `failure_record` with `failure_type="rework"` and auto-generated notes
- Creates an info alert for the PM agent
- The PM must review and update the failure record before the sprint can close (unreviewed rework stubs block sprint completion)

---

## Failure Analysis

Track and analyze failures across the project lifecycle. Failure records capture what went wrong, why, and how it was resolved.

### Recording failures

```
POST /api/failure-records
{
  "project_id": 1,
  "ticket_id": 42,
  "sprint_id": 3,
  "agent_id": 4,
  "logged_by_agent_id": 1,
  "failure_type": "B",
  "severity": "medium",
  "attempt_number": 1,
  "notes": "Agent misunderstood the ticket scope",
  "root_cause": "Ambiguous ticket description"
}
```

### Failure types

| Type | Category |
|------|----------|
| A | Incomplete or incorrect output |
| B | Misunderstood requirements |
| C | Tool/environment failure |
| D | Context loss or hallucination |
| E | Scope creep or over-engineering |
| F | Integration or dependency issue |
| G | Process or communication failure |
| rework | Auto-detected: ticket moved back to in_progress after done |
| test_failure | Auto-detected: individual test failure from a failed test run |

### Auto-detection

Two failure types are created automatically:
- **rework** — when a ticket transitions back to `in_progress` after being `done` (detected via status_history)
- **test_failure** — when a test result is POSTed with `status="failed"`, one record per failed test with nodeid and error message

### Sprint gate

Unreviewed failure records (type "TBD" or auto-detected rework stubs) block sprint completion. The PM must update `failure_type` and `notes` before the sprint can close.

### Summary dashboard

`GET /api/failure-records/summary` returns aggregated data:
- Total / resolved / open counts
- Breakdown by failure type, agent, and sprint
- Trend over time (by date)

Filter by project: `GET /api/failure-records/summary?project_id=1`

---

## API Reference

All endpoints are prefixed with `/api`. Interactive docs at `http://localhost:8000/docs`.

### Projects — `/api/projects`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List projects (filter: `status`) |
| GET | `/api/projects/{id}` | Get project |
| POST | `/api/projects` | Create project |
| POST | `/api/projects/from-repo` | Create project from repo scan |
| PATCH | `/api/projects/{id}` | Update project |
| DELETE | `/api/projects/{id}` | Delete project (cascades) |
| POST | `/api/projects/{id}/overhead` | Increment TL/PM overhead tokens |
| GET | `/api/projects/{id}/gate-status` | Check documentation gates |
| POST | `/api/projects/{id}/scan-tokens` | Trigger token attribution scan |
| POST | `/api/projects/{id}/deploy-playbooks` | Deploy playbooks to project repo |
| GET | `/api/projects/{id}/tests` | List test results for project |

### Epics — `/api/epics`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/epics` | List epics (filter: `project_id`, `status`) |
| GET | `/api/epics/{id}` | Get epic |
| POST | `/api/epics` | Create epic |
| PATCH | `/api/epics/{id}` | Update epic |
| DELETE | `/api/epics/{id}` | Delete epic |

### Sprints — `/api/sprints`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sprints` | List sprints (filter: `project_id`, `status`) |
| GET | `/api/sprints/{id}` | Get sprint |
| POST | `/api/sprints` | Create sprint |
| PATCH | `/api/sprints/{id}` | Update sprint (gates enforced on completion) |
| DELETE | `/api/sprints/{id}` | Delete sprint |

### Tickets — `/api/tickets`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tickets` | List tickets (filter: `project_id`, `sprint_id`, `epic_id`, `assigned_agent_id`, `status`, `ticket_type`) |
| GET | `/api/tickets/{id}` | Get ticket |
| POST | `/api/tickets` | Create ticket (auto-assigns sprint/epic) |
| PATCH | `/api/tickets/{id}` | Update ticket (records status history, computes time) |
| GET | `/api/tickets/{id}/history` | Get status change history |
| GET | `/api/tickets/{id}/token-attribution` | Get token attribution breakdown |
| POST | `/api/tickets/{id}/tokens` | Increment token/time counters |
| DELETE | `/api/tickets/{id}` | Delete ticket |

### Agents — `/api/agents`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List agents (filter: `role`, `is_active`) |
| GET | `/api/agents/{id}` | Get agent |
| POST | `/api/agents` | Create agent |
| PATCH | `/api/agents/{id}` | Update agent |
| DELETE | `/api/agents/{id}` | Delete agent |

### Project Agents — `/api/project-agents`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/project-agents` | List assignments (filter: `project_id`, `agent_id`) |
| GET | `/api/project-agents/{id}` | Get assignment |
| POST | `/api/project-agents` | Assign agent to project |
| DELETE | `/api/project-agents/{id}` | Remove assignment |

### Comments — `/api/comments`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/comments` | List comments (filter: `ticket_id`, `author_agent_id`) |
| GET | `/api/comments/{id}` | Get comment |
| POST | `/api/comments` | Create comment |
| DELETE | `/api/comments/{id}` | Delete comment |

### Alerts — `/api/alerts`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/alerts` | List alerts (filter: `project_id`, `severity`, `status`) |
| GET | `/api/alerts/{id}` | Get alert |
| POST | `/api/alerts` | Create alert |
| PATCH | `/api/alerts/{id}` | Update alert (auto-sets `resolved_at` on resolve) |
| POST | `/api/alerts/dismiss-all` | Bulk dismiss open alerts (filter: `project_id`) |
| POST | `/api/alerts/run-tests` | Request a test run |

### Instructions — `/api/instructions`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/instructions` | List instructions (filter: `scope`, `project_id`, `agent_id`) |
| GET | `/api/instructions/{id}` | Get instruction |
| POST | `/api/instructions` | Create instruction |
| PATCH | `/api/instructions/{id}` | Update instruction |
| DELETE | `/api/instructions/{id}` | Delete instruction |
| GET | `/api/instructions/sync-check` | Compare DB vs memory file instructions |
| POST | `/api/instructions/sync` | Sync memory-only instructions to DB |

### Activity Logs — `/api/activity-logs`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/activity-logs` | List logs (filter: `project_id`, `agent_id`, `entity_type`, `limit`) |
| GET | `/api/activity-logs/{id}` | Get log entry |
| POST | `/api/activity-logs` | Create log entry |

### Test Results — `/api/test-results`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/test-results` | List results (filter: `project_id`, `suite`, `status`, `limit`) |
| GET | `/api/test-results/performance` | Lightweight run history (duration, pass/fail counts) |
| GET | `/api/test-results/{id}` | Get result (includes per-test details) |
| POST | `/api/test-results` | Create result (auto-creates failure records on failure) |

### Failure Records — `/api/failure-records`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/failure-records` | List records (filter: `project_id`, `sprint_id`, `agent_id`, `failure_type`, `resolved`) |
| GET | `/api/failure-records/summary` | Aggregated failure analysis (filter: `project_id`) |
| GET | `/api/failure-records/{id}` | Get record |
| POST | `/api/failure-records` | Create record |
| PATCH | `/api/failure-records/{id}` | Update record |
| DELETE | `/api/failure-records/{id}` | Delete record |

### Tokens — `/api/tokens`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tokens/audit` | Token usage audit (by agent, by project, discrepancies) |

### Playbooks — `/api/playbooks`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/playbooks` | List available playbook files |

### Status — `/api/status`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Health check (active agents, open alerts, in-progress tickets) |
| GET | `/api/status/test-coverage` | Router vs test file coverage report |
| GET | `/api/status/code-standards` | Code header format specification |

---

## Configuration

### Environment variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSQL_HOST` | `127.0.0.1` | Database host |
| `MYSQL_PORT` | `3306` | Database port |
| `MYSQL_DATABASE` | `local_agent_tracker` | Database name |
| `MYSQL_USER` | `lat_user` | Database user |
| `MYSQL_PASSWORD` | `lat_dev_password` | Database password |
| `MYSQL_ROOT_PASSWORD` | `lat_root_password` | Root password (Docker) |
| `API_HOST` | `0.0.0.0` | API bind address |
| `API_PORT` | `8000` | API port |
| `API_RELOAD` | `true` | Auto-reload on code changes |
| `ADMIN_API_KEY` | (placeholder) | Admin API key |
| `PMA_PORT` | `8080` | phpMyAdmin port |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Frontend API base URL |
| `VITE_POLL_INTERVAL_MS` | `2000` | Frontend polling interval (ms) |

### Script variables (all optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `LAT_API_URL` | `http://localhost:8000` | API base URL for all scripts |
| `LAT_DEFAULT_PROJECT_ID` | `1` | Fallback project ID |
| `LAT_TOKEN_SANITY_CAP` | `10000000` | Max tokens per transcript before flagging |
| `LAT_TOKEN_STATE_FILE` | `/tmp/lat_token_attribution_state.json` | State file for scan dedup |
| `LAT_TRANSCRIPT_DIR` | (auto-detected) | Override transcript scan directory |
| `ACTIVE_TICKET_ID` | (auto-detected) | Override ticket for stop hook attribution |
| `ACTIVE_PROJECT_ID` | `1` | Override project for stop hook |
| `ACTIVE_AGENT_ID` | (auto-detected) | Override agent for stop hook |

### Project structure

```
local_agent_tracker/
├── .env                    # Environment config
├── docker-compose.yml      # MySQL + phpMyAdmin
├── seed.sql                # Sample data
├── INITIAL.md              # Project origins document
├── ARCHITECTURE.md         # Technical architecture reference
├── QUICKSTART.md           # Quick setup commands
├── docs/
│   ├── team_lead_playbook.md
│   ├── pm_playbook.md
│   └── ROADMAP_PHASE2.md
├── backend/
│   ├── alembic/            # Database migrations
│   ├── app/
│   │   ├── main.py         # FastAPI app + CORS + router registration
│   │   ├── config.py       # Pydantic Settings
│   │   ├── database.py     # Engine + session factory
│   │   ├── models/         # SQLAlchemy models (13 tables)
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   ├── services/       # Business logic layer
│   │   └── routers/        # HTTP endpoint handlers (15 routers)
│   ├── scripts/
│   │   ├── report_tokens.py      # Claude Code stop hook
│   │   ├── attribute_tokens.py   # Transcript scanner for token attribution
│   │   ├── run_token_scan.sh     # Shell wrapper for attribute_tokens.py
│   │   ├── run_tests.sh          # Test runner with API reporting
│   │   └── sync_instructions.py  # Memory/file ↔ DB sync
│   └── tests/              # Pytest test suite
└── frontend/
    ├── src/
    │   ├── api/            # API client modules
    │   ├── components/     # React components
    │   ├── hooks/          # Data fetching + polling
    │   ├── pages/          # Route pages
    │   ├── store/          # Zustand state
    │   └── styles/         # CSS (dark terminal theme)
    └── package.json
```
