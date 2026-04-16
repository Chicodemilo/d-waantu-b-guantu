# D'Waantu B'Guantu (DWB)

A multi-agent workflow dashboard for tracking Claude Code teammate progress, managing sprints, enforcing completion gates, and accounting for time and token spend. Built to coordinate autonomous AI agents working as a software team — each running as a Claude Code teammate with auto-loaded playbooks.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Core Concepts](#core-concepts)
- [Agent Definitions](#agent-definitions)
- [Tracking (Time & Tokens)](#tracking-time--tokens)
- [Sprint Gates](#sprint-gates)
- [Failure Analysis](#failure-analysis)
- [Activity Feed](#activity-feed)
- [Testing](#testing)
- [Adding a Project](#adding-a-project)
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

### 3. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard at `http://localhost:5173`.

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

**Backend** — FastAPI with SQLAlchemy 2.0, Pydantic v2, three-layer architecture:
- `app/routers/` — 17 router files, 87 HTTP endpoints
- `app/services/` — business logic, validation, automation triggers
- `app/models/` — 15 SQLAlchemy models (15 tables)
- `app/schemas/` — Pydantic request/response models
- `app/middleware/` — activity logging middleware

**Frontend** — React 18 with Vite, Zustand state management, React Router. Vanilla CSS with dark terminal aesthetic (JetBrains Mono, green/orange/blue on black). Adaptive polling: 2s when sprints are active, 10s when idle.

**Database** — MySQL 8.0 via PyMySQL. Alembic manages migrations with autogenerate support.

---

## Core Concepts

### Hierarchy

```
Project → Epic → Sprint → Ticket
```

Every ticket MUST have a sprint, every sprint an epic, every epic a project. Enforced at the API level — missing parents return 400.

**Projects** have a unique prefix (e.g., `DWB`) for ticket keys, optional `repo_path` for filesystem validation, and 7 sprint gate toggles.

**Epics** group related work. Statuses: `open` → `in_progress` → `completed`.

**Sprints** are time-boxed iterations under an epic. Statuses: `planned` → `active` → `completed`. Sprint names are auto-generated from goals. Completing a sprint triggers gate validation, token scan, alerts, and auto-test-ticket creation.

**Tickets** are work items with a `ticket_key` (e.g., `DWB-042`), type (`task`/`bug`/`story`), and status (`backlog` → `todo` → `in_progress` → `in_review` → `done` / `cancelled`).

### Auto-assignment

- **Ticket without `sprint_id`** — assigned to the most recent active sprint
- **Ticket without `epic_id`** — inherits from the sprint's epic
- **Sprint without `epic_id`** — assigned to the most recent open/in-progress epic

---

## Agent Definitions

Agent definitions live in `.claude/agents/`. Spawning a teammate by name auto-loads their full playbook — no manual file reading needed.

| Spawn as | Definition file | Role |
|----------|----------------|------|
| `@team-lead` | `.claude/agents/team-lead.md` | Orchestrator — plans sprints, assigns work |
| `@pm` | `.claude/agents/pm.md` | Project manager — monitors, manages tickets, logs failures |
| `@frontend-worker` | `.claude/agents/frontend-worker.md` | React, Vite, Zustand, plain CSS |
| `@backend-worker` | `.claude/agents/backend-worker.md` | FastAPI, SQLAlchemy 2.0, Alembic |
| `@system-ops` | `.claude/agents/system-ops.md` | Docker, scripts, infrastructure |
| `@tester` | `.claude/agents/tester.md` | pytest, vitest, test coverage, bug filing |

All workers also receive the general worker playbook: `.claude/agents/worker.md`.

**The PM is mandatory on every team.** Minimum team: `@team-lead` + `@pm`. Add workers as needed.

### Deployable Playbooks

Master playbooks live in `docs/` and are deployed to other project repos via `POST /api/projects/{id}/deploy-playbooks`:

| Playbook | File | Audience |
|----------|------|----------|
| Team Lead | `docs/team_lead_playbook.md` | TL agents |
| PM | `docs/pm_playbook.md` | PM agents |
| Worker | `docs/worker_playbook.md` | All agents |

### TEAM.md

Each project should have a `TEAM.md` at the repo root defining the team roster (name, duty, playbook path) and session continuity notes. Enforced by the `force_team_md` gate (enabled by default on all projects). A template is available at `.claude/agents/TEAM.md.template`.

Agents are assigned to projects via `project_agents`. This controls alert routing and enables dynamic role lookups — no hardcoded agent IDs in business logic.

### X-Agent-ID Header

Include `X-Agent-ID: {agent_id}` on all mutating requests (POST, PATCH, PUT, DELETE). The activity logging middleware uses this header to attribute actions to agents in the activity feed. Without it, the system falls back to response body heuristics and project role lookups.

---

## Tracking (Time & Tokens)

The `tracking_log` table is the **source of truth** for time and token accounting. It records discrete events: `start`, `stop`, `token_report`, `overhead_start`, `overhead_stop`.

### How it works

**Time tracking** — `start`/`stop` event pairs per ticket. Total time = sum of intervals between paired events. Status transitions auto-insert tracking events:
- Status → `in_progress`: auto `start`
- Status from `in_progress` → anything: auto `stop`
- Status directly to `done` (skipping `in_progress`): auto `start` + `stop` pair so every completed ticket has a record

**Token tracking** — `token_report` events with a token count and source. Sources: `transcript_scan`, `manual`, `auto`.

**Overhead tracking** — `overhead_start`/`overhead_stop` events for non-ticket work (TL/PM coordination time), tracked at the project level.

### Tracking API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tracking/start` | Log work start `{ticket_id, agent_id}` |
| POST | `/api/tracking/stop` | Log work stop `{ticket_id, agent_id}` |
| POST | `/api/tracking/tokens` | Report tokens `{ticket_id, agent_id, tokens, source}` |
| POST | `/api/tracking/overhead/start` | Start overhead `{project_id, agent_id}` |
| POST | `/api/tracking/overhead/stop` | Stop overhead `{project_id, agent_id}` |
| GET | `/api/tracking/summary?project_id=X` | Full breakdown: per-ticket, per-agent, per-sprint, project totals |

### Hook-based tracking (passive — primary)

Time and tokens are captured **automatically** via Claude Code lifecycle hooks. No agent awareness needed.

- **SessionStart** hook → `POST /api/hooks/session-start` → creates `hook_session` record, logs start event
- **SessionEnd** hook → `POST /api/hooks/session-end` → parses JSONL transcript for tokens, resolves agent identity, logs stop + token events
- **SubagentStop** hook → same as SessionEnd for teammate transcripts

Hook configuration lives in `.claude/settings.json`. Hooks fire automatically — zero manual intervention.

The `hook_sessions` table tracks session state (active/completed). The `tracking_log` table remains the authoritative ledger — hooks delegate to `log_start()`, `log_stop()`, `log_tokens()`, `log_overhead_start/stop()`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/hooks/session-start` | Receive SessionStart hook data |
| POST | `/api/hooks/session-end` | Receive SessionEnd/SubagentStop hook data |
| GET | `/api/hooks/sessions` | List hook sessions (filters: project_id, status) |
| GET | `/api/hooks/sessions/{id}` | Get session by session_id |

### Transcript scanning (manual fallback)

`scripts/attribute_tokens.py` scans Claude Code transcript files and attributes tokens to tickets. Kept as a manual fallback for backfilling or recovery.

Trigger via API: `POST /api/projects/{id}/scan-tokens`

### Legacy endpoints

`POST /api/tickets/{id}/tokens` and `GET /api/tickets/{id}/token-attribution` still exist for backwards compatibility but the tracking API is the primary interface. `GET /api/tokens/audit` aggregates across both systems.

---

## Sprint Gates

Seven boolean toggles that gate sprint completion:

| Toggle | What it checks |
|--------|---------------|
| `force_test_run` | At least one test run since sprint start date |
| `force_test_coverage` | Every router has a corresponding test file |
| `force_initial_md` | `INITIAL.md` exists at repo root |
| `force_architecture_md` | `ARCHITECTURE.md` exists at repo root |
| `force_team_md` | `TEAM.md` exists at repo root (default: enabled) |
| `force_headers` | Reserved for v2 |
| Failure records | Unreviewed stubs block close (always enforced) |

Additionally, **unreviewed failure records** on sprint tickets block closure. If any `failure_record` has `failure_type="TBD"` or is an auto-detected rework stub, the PM must review it first.

`GET /api/projects/{id}/gate-status` checks each gate and auto-creates alerts for failures.

### On sprint completion

1. Alerts created for team-lead, PM, and tester (looked up by role)
2. Test ticket auto-created for the next active sprint
3. Token attribution scan runs automatically

---

## Failure Analysis

### Auto-detection

- **Rework** — ticket moves back to `in_progress` after `done` → creates `failure_record` + PM alert
- **Test failure** — failed test result POSTed → one `failure_record` per failed test

### Failure types

| Type | Category |
|------|----------|
| A–G | Manual taxonomy (incomplete output, misunderstood requirements, tool failure, etc.) |
| rework | Auto-detected: ticket reopened |
| test_failure | Auto-detected: individual test failure |

### Sprint gate

Unreviewed stubs (type "TBD" or auto-detected rework) block sprint close until the PM reviews them.

`GET /api/failure-records/summary` returns aggregated breakdowns by type, agent, sprint, and trend.

---

## Activity Feed

The activity logging middleware intercepts all POST/PATCH/DELETE responses and auto-inserts into `activity_log`. Agent attribution uses the `X-Agent-ID` header (priority) with fallback to response body fields and project role lookups.

- `GET /api/projects/{id}/activity-feed?limit=50` — newest first, joins agent names and roles
- `GET /api/activity-logs` — raw log entries with filters

---

## Testing

Tests live in `backend/tests/` using pytest with transactional rollback per test against a `lat_test` database.

```bash
cd backend && pytest tests/
```

With API reporting:

```bash
./scripts/run_tests.sh --post --project-id 1 --triggered-by "manual"
```

Or trigger via API: `POST /api/system/run-tests`

`GET /api/status/test-coverage` reports which routers have corresponding test files.
`GET /api/test-results/performance` returns run history for trend analysis.

---

## Adding a Project

### Demo project (quick start)

```
POST /api/projects/seed-demo
```

Creates a fully-populated demo project (prefix `DMO`) with 5 agents, 3 epics, 6 sprints, 30 tickets, test results, failure records, and alerts. Idempotent — re-seeding deletes and recreates the DMO project. Also creates a fake repo at `/tmp/dwb-demo-project` with README.md, INITIAL.md, ARCHITECTURE.md, and TEAM.md so doc gates pass. Great for testing the dashboard without setting up a real project.

### From repo (recommended)

```
POST /api/projects/from-repo
{"repo_path": "/path/to/repo"}
```

Auto-detects name, prefix, description. Enables doc gates by default.

### Onboarding flow

1. Check gates: `GET /api/projects/{id}/gate-status`
2. Assign agents: `POST /api/project-agents`
3. Create epic: `POST /api/epics`
4. Create sprint: `POST /api/sprints` with a goal
5. Deploy playbooks: `POST /api/projects/{id}/deploy-playbooks`
6. Create tickets and begin work

---

## API Reference

All endpoints prefixed with `/api`. Interactive docs at `http://localhost:8000/docs`. 83 endpoints across 16 routers.

### Projects — `/api/projects`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List projects |
| GET | `/api/projects/{id}` | Get project |
| POST | `/api/projects` | Create project |
| POST | `/api/projects/from-repo` | Create from repo scan |
| POST | `/api/projects/seed-demo` | Seed demo project (idempotent) |
| PATCH | `/api/projects/{id}` | Update project |
| DELETE | `/api/projects/{id}` | Delete project |
| POST | `/api/projects/{id}/overhead` | Increment overhead tokens |
| GET | `/api/projects/{id}/gate-status` | Check documentation gates |
| POST | `/api/projects/{id}/scan-tokens` | Trigger token attribution scan |
| POST | `/api/projects/{id}/deploy-playbooks` | Deploy playbooks to repo |
| GET | `/api/projects/{id}/tests` | List test results |
| GET | `/api/projects/{id}/activity-feed` | Activity feed (newest first) |
| GET | `/api/projects/{id}/docs` | Scan project doc files |

### Epics — `/api/epics`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/epics` | List epics |
| GET | `/api/epics/{id}` | Get epic |
| POST | `/api/epics` | Create epic |
| PATCH | `/api/epics/{id}` | Update epic |
| DELETE | `/api/epics/{id}` | Delete epic |

### Sprints — `/api/sprints`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sprints` | List sprints |
| GET | `/api/sprints/{id}` | Get sprint |
| POST | `/api/sprints` | Create sprint |
| PATCH | `/api/sprints/{id}` | Update sprint (gates on completion) |
| DELETE | `/api/sprints/{id}` | Delete sprint |

### Tickets — `/api/tickets`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tickets` | List tickets (many filters) |
| GET | `/api/tickets/{id}` | Get ticket |
| POST | `/api/tickets` | Create ticket (auto-assigns sprint/epic) |
| PATCH | `/api/tickets/{id}` | Update ticket (records history, auto-tracks) |
| DELETE | `/api/tickets/{id}` | Delete ticket |
| GET | `/api/tickets/{id}/history` | Status change history |
| GET | `/api/tickets/{id}/token-attribution` | Token attribution breakdown |
| POST | `/api/tickets/{id}/tokens` | Increment token counters (legacy) |

### Tracking — `/api/tracking`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tracking/start` | Log work start |
| POST | `/api/tracking/stop` | Log work stop |
| POST | `/api/tracking/tokens` | Report tokens |
| POST | `/api/tracking/overhead/start` | Start overhead tracking |
| POST | `/api/tracking/overhead/stop` | Stop overhead tracking |
| GET | `/api/tracking/summary` | Project tracking summary |

### Agents — `/api/agents`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List agents |
| GET | `/api/agents/{id}` | Get agent |
| POST | `/api/agents` | Create agent |
| PATCH | `/api/agents/{id}` | Update agent |
| DELETE | `/api/agents/{id}` | Delete agent |

### Project Agents — `/api/project-agents`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/project-agents` | List assignments |
| GET | `/api/project-agents/{id}` | Get assignment |
| POST | `/api/project-agents` | Assign agent to project |
| DELETE | `/api/project-agents/{id}` | Remove assignment |

### Alerts — `/api/alerts`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/alerts` | List alerts |
| GET | `/api/alerts/{id}` | Get alert |
| POST | `/api/alerts` | Create alert |
| PATCH | `/api/alerts/{id}` | Update alert |
| POST | `/api/alerts/dismiss-all` | Bulk dismiss open alerts |
| POST | `/api/alerts/run-tests` | Request a test run |

### Comments — `/api/comments`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/comments` | List comments |
| GET | `/api/comments/{id}` | Get comment |
| POST | `/api/comments` | Create comment |
| DELETE | `/api/comments/{id}` | Delete comment |

### Instructions — `/api/instructions`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/instructions` | List instructions |
| GET | `/api/instructions/{id}` | Get instruction |
| POST | `/api/instructions` | Create instruction |
| PATCH | `/api/instructions/{id}` | Update instruction |
| DELETE | `/api/instructions/{id}` | Delete instruction |
| GET | `/api/instructions/sync-check` | Compare DB vs memory files |
| POST | `/api/instructions/sync` | Sync memory-only to DB |

### Activity Logs — `/api/activity-logs`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/activity-logs` | List logs |
| GET | `/api/activity-logs/{id}` | Get log entry |
| POST | `/api/activity-logs` | Create log entry |

### Test Results — `/api/test-results`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/test-results` | List results |
| GET | `/api/test-results/performance` | Run history for trends |
| GET | `/api/test-results/{id}` | Get result with details |
| POST | `/api/test-results` | Create result (auto-creates failure records) |

### Failure Records — `/api/failure-records`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/failure-records` | List records |
| GET | `/api/failure-records/summary` | Aggregated failure analysis |
| GET | `/api/failure-records/{id}` | Get record |
| POST | `/api/failure-records` | Create record |
| PATCH | `/api/failure-records/{id}` | Update record |
| DELETE | `/api/failure-records/{id}` | Delete record |

### Tokens — `/api/tokens`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tokens/audit` | Token usage audit |

### Hooks — `/api/hooks`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/hooks/session-start` | Receive SessionStart hook data |
| POST | `/api/hooks/session-end` | Receive SessionEnd/SubagentStop hook data |
| GET | `/api/hooks/sessions` | List hook sessions |
| GET | `/api/hooks/sessions/{id}` | Get session by ID |

### Playbooks — `/api/playbooks`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/playbooks` | List available playbooks (TL, PM, worker) |

### System — `/api/system`, `/api/status`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Health check |
| GET | `/api/status/test-coverage` | Router test coverage |
| GET | `/api/status/code-standards` | Code header format |
| GET | `/api/system/docs` | System documentation files |
| POST | `/api/system/run-tests` | Trigger test suite |

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
| `API_RELOAD` | `true` | Auto-reload on changes |
| `ADMIN_API_KEY` | (placeholder) | Admin API key |
| `PMA_PORT` | `8080` | phpMyAdmin port |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Frontend API base |
| `VITE_POLL_INTERVAL_MS` | `2000` | Frontend polling interval (ms) |

### Script variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LAT_API_URL` | `http://localhost:8000` | API base for scripts |
| `LAT_DEFAULT_PROJECT_ID` | `1` | Fallback project ID |
| `LAT_TOKEN_SANITY_CAP` | `10000000` | Max tokens per transcript |
| `LAT_TOKEN_STATE_FILE` | `/tmp/lat_token_attribution_state.json` | Scan dedup state |
| `LAT_TRANSCRIPT_DIR` | (auto-detected) | Override transcript directory |

### Project structure

```
d-waantu_b-guantu/
├── .env
├── docker-compose.yml
├── seed.sql
├── CLAUDE.md                # Team lead instructions
├── INITIAL.md
├── ARCHITECTURE.md
├── QUICKSTART.md
├── TEAM.md                  # Team roster + session continuity
├── .claude/agents/          # Agent definitions (auto-loaded by Claude Code)
│   ├── team-lead.md
│   ├── pm.md
│   ├── frontend-worker.md
│   ├── backend-worker.md
│   ├── system-ops.md
│   ├── tester.md
│   ├── worker.md            # General worker playbook (all agents)
│   └── TEAM.md.template     # Template for new project TEAM.md files
├── docs/                    # Deployable playbooks (pushed to other projects)
│   ├── team_lead_playbook.md
│   ├── pm_playbook.md
│   ├── worker_playbook.md
│   └── PASSIVE_TRACKING_PLAN.md
├── backend/
│   ├── alembic/             # Database migrations
│   ├── app/
│   │   ├── main.py          # FastAPI app + middleware + routers
│   │   ├── config.py        # Pydantic Settings
│   │   ├── database.py      # Engine + session factory
│   │   ├── middleware/       # Activity logging middleware
│   │   ├── models/          # 15 SQLAlchemy models (incl. hook_session)
│   │   ├── schemas/         # Pydantic request/response
│   │   ├── services/        # Business logic layer
│   │   └── routers/         # 17 HTTP router files (incl. hooks)
│   ├── scripts/
│   │   ├── attribute_tokens.py   # Transcript scanner → /api/tracking/tokens
│   │   ├── run_token_scan.sh     # Shell wrapper
│   │   ├── run_tests.sh          # Test runner with API reporting
│   │   └── sync_instructions.py  # Memory/file ↔ DB sync
│   └── tests/
└── frontend/
    ├── src/
    │   ├── api/             # API client modules
    │   ├── components/      # React components
    │   ├── hooks/           # Data fetching + polling
    │   ├── pages/           # Route pages
    │   ├── store/           # Zustand state
    │   └── styles/          # CSS (dark terminal theme)
    └── package.json
```
