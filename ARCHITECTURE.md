# Architecture

Technical reference for the Local Agent Tracker (LAT) system.

```
┌─────────────────────────────────────────────────────────┐
│                    Local Agent Tracker                   │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  React    │───▶│  FastAPI     │───▶│  MySQL 8.0    │  │
│  │  :5173    │◀───│  :8000       │◀───│  :23847       │  │
│  └──────────┘    └──────────────┘    └───────────────┘  │
│       │               ▲                     ▲           │
│       │               │                     │           │
│       │          ┌────┴─────┐         ┌─────┴─────┐     │
│       │          │ Scripts  │         │ phpMyAdmin │     │
│       │          │ & Hooks  │         │   :8080    │     │
│       │          └──────────┘         └───────────┘     │
│       │                                                 │
│  Vite dev server                Docker Compose          │
│  polls /api/status              manages DB + PMA        │
│  adaptive 2s/10s                                        │
└─────────────────────────────────────────────────────────┘
```

---

## 1. System Overview

Three-tier architecture for tracking AI agent work across projects, sprints, and tickets.

| Layer    | Technology           | Port  | Purpose                          |
|----------|----------------------|-------|----------------------------------|
| Frontend | React 18 + Vite      | 5173  | Dashboard, project management UI |
| Backend  | FastAPI + SQLAlchemy  | 8000  | REST API, business logic         |
| Database | MySQL 8.0 (Docker)   | 23847 | Persistent storage               |
| Admin    | phpMyAdmin (Docker)   | 8080  | DB administration                |

The frontend polls the backend with adaptive intervals (2s when agents are active, 10s when idle). The backend follows a router → service → model pattern. Scripts handle test execution, token attribution, and instruction sync.

---

## 2. Data Model

### Entity Hierarchy

```
Project
├── Epic
│   └── (tickets grouped by epic)
├── Sprint
│   └── Ticket
│       ├── StatusHistory (every status transition)
│       ├── Comment
│       ├── FailureRecord (optional)
│       └── Alert (optional)
├── ProjectAgent (join table)
├── Instruction (scoped)
├── ActivityLog
├── TestResult
├── FailureRecord (project-level)
└── Alert (project-level)

Agent (standalone)
├── ProjectAgent (assigned to projects)
├── Ticket (assigned work)
├── Comment (authored)
├── Alert (raised)
├── FailureRecord (agent + logged_by_agent)
├── StatusHistory (changed_by_agent)
└── Instruction (scoped to agent)
```

### Tables

#### projects
| Column                   | Type         | Notes                                    |
|--------------------------|--------------|------------------------------------------|
| id                       | BIGINT PK    | Auto-increment                           |
| prefix                   | VARCHAR(10)  | Unique, e.g. "DWB"                       |
| name                     | VARCHAR(255) |                                          |
| description              | TEXT         |                                          |
| status                   | ENUM         | active, paused, completed, archived      |
| repo_path                | VARCHAR(500) | Local filesystem path                    |
| jira_base_url            | VARCHAR(500) | Optional external tracker                |
| tl_overhead_tokens       | BIGINT       | Team lead overhead accumulator           |
| pm_overhead_tokens       | BIGINT       | PM overhead accumulator                  |
| tl_overhead_time_seconds | BIGINT       |                                          |
| pm_overhead_time_seconds | BIGINT       |                                          |
| force_headers            | BOOL         | Sprint gate: require code headers (v2)   |
| force_test_coverage      | BOOL         | Sprint gate: require test coverage       |
| force_test_run           | BOOL         | Sprint gate: require passing test run    |
| force_initial_md         | BOOL         | Sprint gate: require INITIAL.md          |
| force_architecture_md    | BOOL         | Sprint gate: require ARCHITECTURE.md     |
| created_at, updated_at   | DATETIME     |                                          |

#### sprints
| Column        | Type         | Notes                          |
|---------------|--------------|--------------------------------|
| id            | BIGINT PK    |                                |
| project_id    | FK→projects  |                                |
| epic_id       | FK→epics     | Required (auto-assigned)       |
| name          | VARCHAR(255) | Auto-generated from goal       |
| goal          | TEXT         |                                |
| sprint_number | INT          |                                |
| status        | ENUM         | planned, active, completed     |
| start_date    | DATE         |                                |
| end_date      | DATE         |                                |

Completion triggers: validates 5 sprint gates + unreviewed failure records, creates alerts for team-lead/pm/tester, auto-creates test ticket for next sprint, runs token attribution scan.

#### epics
| Column      | Type         | Notes                              |
|-------------|--------------|------------------------------------|
| id          | BIGINT PK    |                                    |
| project_id  | FK→projects  |                                    |
| name        | VARCHAR(255) |                                    |
| description | TEXT         |                                    |
| status      | ENUM         | open, in_progress, completed       |

#### agents
| Column      | Type         | Notes                                      |
|-------------|--------------|--------------------------------------------|
| id          | BIGINT PK    |                                            |
| name        | VARCHAR(255) | Human name (Archie, Bolt, Pixel...)        |
| description | TEXT         |                                            |
| role        | VARCHAR(100) | Claude teammate name (team-lead, system-ops)|
| api_key     | VARCHAR(255) | Unique                                     |
| is_active   | BOOL         |                                            |

#### project_agents
| Column     | Type        | Notes                                 |
|------------|-------------|---------------------------------------|
| id         | BIGINT PK   |                                       |
| project_id | FK→projects | Unique constraint: (project_id, agent_id) |
| agent_id   | FK→agents   |                                       |
| assigned_at| DATETIME    |                                       |

#### tickets
| Column            | Type         | Notes                                     |
|-------------------|--------------|-------------------------------------------|
| id                | BIGINT PK    |                                           |
| project_id        | FK→projects  |                                           |
| epic_id           | FK→epics     | Nullable                                  |
| sprint_id         | FK→sprints   | Auto-assigned to active sprint            |
| assigned_agent_id | FK→agents    | Nullable                                  |
| ticket_number     | INT          |                                           |
| ticket_key        | VARCHAR(50)  | Unique, e.g. "DWB-042"                   |
| title             | VARCHAR(500) |                                           |
| description       | TEXT         |                                           |
| ticket_type       | ENUM         | task, bug, story                          |
| status            | ENUM         | backlog, todo, in_progress, in_review, done|
| tokens_used       | BIGINT       | Cumulative token count                    |
| time_spent_seconds| BIGINT       | Auto-computed from status_history         |
| token_source      | VARCHAR(50)  | transcript_scan, manual_estimate, unknown |
| completed_at      | DATETIME     |                                           |
| created_at        | DATETIME     |                                           |
| updated_at        | DATETIME     |                                           |

On status change: records StatusHistory, recomputes time_spent_seconds, detects rework. Auto-creates alert when marked done with 0 tokens.

#### status_history
| Column              | Type        | Notes                          |
|---------------------|-------------|--------------------------------|
| id                  | BIGINT PK   |                                |
| ticket_id           | FK→tickets  | NOT NULL, indexed              |
| old_status          | VARCHAR(50) |                                |
| new_status          | VARCHAR(50) |                                |
| changed_at          | DATETIME    | Default: now()                 |
| changed_by_agent_id | FK→agents   | Nullable                       |

Used for: time-in-progress computation, rework detection, ticket timeline UI.

#### failure_records
| Column            | Type        | Notes                                        |
|-------------------|-------------|----------------------------------------------|
| id                | BIGINT PK   |                                              |
| project_id        | FK→projects | NOT NULL, indexed                            |
| ticket_id         | FK→tickets  | Nullable, indexed                            |
| sprint_id         | FK→sprints  | NOT NULL, indexed                            |
| agent_id          | FK→agents   | NOT NULL (the agent who failed)              |
| logged_by_agent_id| FK→agents   | NOT NULL (who recorded it)                   |
| failure_type      | VARCHAR(50) | A-G, rework, test_failure, TBD               |
| severity          | VARCHAR(20) | low, medium, high, critical                  |
| attempt_number    | INT         | Default: 2                                   |
| notes             | TEXT        |                                              |
| root_cause        | TEXT        |                                              |
| resolution        | TEXT        |                                              |
| resolved          | BOOL        | Default: false                               |
| created_at        | DATETIME    |                                              |
| updated_at        | DATETIME    |                                              |

Two FK relationships to agents (agent_id + logged_by_agent_id) using `foreign_keys=` parameter. Unreviewed stubs (type=TBD or auto-detected rework) block sprint close.

#### comments
| Column          | Type       | Notes          |
|-----------------|------------|----------------|
| id              | BIGINT PK  |                |
| ticket_id       | FK→tickets |                |
| author_agent_id | FK→agents  |                |
| body            | TEXT       |                |
| created_at      | DATETIME   |                |

#### alerts
| Column             | Type        | Notes                                |
|--------------------|-------------|--------------------------------------|
| id                 | BIGINT PK   |                                      |
| project_id         | FK→projects |                                      |
| raised_by_agent_id | FK→agents   |                                      |
| ticket_id          | FK→tickets  | Nullable                             |
| title              | VARCHAR(500)|                                      |
| body               | TEXT        |                                      |
| severity           | ENUM        | info, warning, critical              |
| status             | ENUM        | open, acknowledged, resolved         |
| resolved_at        | DATETIME    | Auto-set when status→resolved        |

#### instructions
| Column     | Type        | Notes                                 |
|------------|-------------|---------------------------------------|
| id         | BIGINT PK   |                                       |
| scope      | ENUM        | global, project, agent                |
| project_id | FK→projects | Nullable (for project scope)          |
| agent_id   | FK→agents   | Nullable (for agent scope)            |
| title      | VARCHAR(500)|                                       |
| body       | TEXT        |                                       |

#### activity_log
| Column      | Type        | Notes                            |
|-------------|-------------|----------------------------------|
| id          | BIGINT PK   |                                  |
| project_id  | FK→projects |                                  |
| agent_id    | FK→agents   | Nullable                         |
| entity_type | VARCHAR(50) | e.g. "ticket", "sprint"          |
| entity_id   | INT         |                                  |
| action      | VARCHAR(50) | e.g. "created", "updated"        |
| details     | TEXT        | JSON-encoded details             |
| created_at  | DATETIME    |                                  |

#### test_results
| Column            | Type         | Notes                         |
|-------------------|--------------|-------------------------------|
| id                | BIGINT PK    |                               |
| project_id        | FK→projects  |                               |
| sprint_id         | FK→sprints   | Nullable                      |
| ticket_id         | FK→tickets   | Nullable                      |
| run_at            | DATETIME     |                               |
| suite             | VARCHAR(100) | e.g. "backend"                |
| total_tests       | INT          |                               |
| passed            | INT          |                               |
| failed            | INT          |                               |
| skipped           | INT          |                               |
| duration_seconds  | FLOAT        |                               |
| status            | ENUM         | passed, failed, error         |
| details           | TEXT         | JSON with per-test results    |
| triggered_by      | VARCHAR(100) | e.g. "manual", "agent:tester" |
| triggered_context | VARCHAR(200) | Optional description          |

On create with status="failed": auto-creates failure_records for each failed test in details JSON.

---

## 3. API Layer

### Pattern: Router → Service → Model

```
Request → Router (validation, HTTP) → Service (business logic) → Model (ORM) → DB
                  ↓                         ↓
            Pydantic schemas         SQLAlchemy queries
```

- **Routers** (`app/routers/`): Define endpoints, validate input via Pydantic, inject DB session via `Depends(get_db)`. 15 router files.
- **Services** (`app/services/`): Business logic, cross-entity operations, auto-triggers (status history, rework detection, time computation, failure records, token attribution). 14 service files.
- **Models** (`app/models/`): SQLAlchemy 2.0 ORM classes with Mapped types and relationships. 13 model files.
- **Schemas** (`app/schemas/`): Pydantic v2 models with ConfigDict(from_attributes=True) for Create, Update, Read per entity. 13 schema files.

### Endpoint Reference

#### /api/projects
| Method | Path                              | Query Params | Purpose                    |
|--------|-----------------------------------|--------------|----------------------------|
| GET    | /api/projects                     | status       | List projects              |
| GET    | /api/projects/{id}                |              | Get project                |
| POST   | /api/projects                     |              | Create project             |
| POST   | /api/projects/from-repo           |              | Create from repo scan      |
| PATCH  | /api/projects/{id}                |              | Update project             |
| POST   | /api/projects/{id}/overhead       |              | Increment overhead tokens  |
| DELETE | /api/projects/{id}                |              | Delete (cascades all)      |
| GET    | /api/projects/{id}/gate-status    |              | Check doc gates + alert    |
| POST   | /api/projects/{id}/scan-tokens    |              | Trigger token attribution  |
| POST   | /api/projects/{id}/deploy-playbooks|             | Deploy playbooks to repo   |
| GET    | /api/projects/{id}/tests          | suite, status, limit | Project test runs  |

#### /api/sprints
| Method | Path                | Query Params       | Purpose        |
|--------|---------------------|--------------------|----------------|
| GET    | /api/sprints        | project_id, status | List sprints   |
| GET    | /api/sprints/{id}   |                    | Get sprint     |
| POST   | /api/sprints        |                    | Create sprint  |
| PATCH  | /api/sprints/{id}   |                    | Update sprint  |
| DELETE | /api/sprints/{id}   |                    | Delete sprint  |

#### /api/epics
| Method | Path             | Query Params       | Purpose      |
|--------|------------------|--------------------|--------------|
| GET    | /api/epics       | project_id, status | List epics   |
| GET    | /api/epics/{id}  |                    | Get epic     |
| POST   | /api/epics       |                    | Create epic  |
| PATCH  | /api/epics/{id}  |                    | Update epic  |
| DELETE | /api/epics/{id}  |                    | Delete epic  |

#### /api/agents
| Method | Path              | Query Params     | Purpose       |
|--------|-------------------|------------------|---------------|
| GET    | /api/agents       | role, is_active  | List agents   |
| GET    | /api/agents/{id}  |                  | Get agent     |
| POST   | /api/agents       |                  | Create agent  |
| PATCH  | /api/agents/{id}  |                  | Update agent  |
| DELETE | /api/agents/{id}  |                  | Delete agent  |

#### /api/project-agents
| Method | Path                    | Query Params          | Purpose          |
|--------|-------------------------|-----------------------|------------------|
| GET    | /api/project-agents     | project_id, agent_id  | List assignments |
| GET    | /api/project-agents/{id}|                       | Get assignment   |
| POST   | /api/project-agents     |                       | Create           |
| DELETE | /api/project-agents/{id}|                       | Delete           |

#### /api/tickets
| Method | Path                               | Query Params                                                    | Purpose             |
|--------|------------------------------------|-----------------------------------------------------------------|---------------------|
| GET    | /api/tickets                       | project_id, sprint_id, epic_id, assigned_agent_id, status, type | List tickets        |
| GET    | /api/tickets/{id}                  |                                                                 | Get ticket          |
| POST   | /api/tickets                       |                                                                 | Create ticket       |
| PATCH  | /api/tickets/{id}                  |                                                                 | Update ticket       |
| GET    | /api/tickets/{id}/history          |                                                                 | Status history      |
| GET    | /api/tickets/{id}/token-attribution|                                                                 | Token breakdown     |
| POST   | /api/tickets/{id}/tokens           |                                                                 | Increment tokens    |
| DELETE | /api/tickets/{id}                  |                                                                 | Delete ticket       |

#### /api/comments
| Method | Path                 | Query Params               | Purpose        |
|--------|----------------------|----------------------------|----------------|
| GET    | /api/comments        | ticket_id, author_agent_id | List comments  |
| GET    | /api/comments/{id}   |                            | Get comment    |
| POST   | /api/comments        |                            | Create comment |
| DELETE | /api/comments/{id}   |                            | Delete comment |

#### /api/alerts
| Method | Path                    | Query Params                  | Purpose            |
|--------|-------------------------|-------------------------------|--------------------|
| GET    | /api/alerts             | project_id, severity, status  | List alerts        |
| GET    | /api/alerts/{id}        |                               | Get alert          |
| POST   | /api/alerts             |                               | Create alert       |
| PATCH  | /api/alerts/{id}        |                               | Update alert       |
| POST   | /api/alerts/dismiss-all |                               | Dismiss all open   |
| POST   | /api/alerts/run-tests   |                               | Trigger test run   |

#### /api/instructions
| Method | Path                         | Query Params               | Purpose              |
|--------|------------------------------|----------------------------|----------------------|
| GET    | /api/instructions            | scope, project_id, agent_id| List instructions    |
| GET    | /api/instructions/{id}       |                            | Get instruction      |
| POST   | /api/instructions            |                            | Create instruction   |
| PATCH  | /api/instructions/{id}       |                            | Update instruction   |
| DELETE | /api/instructions/{id}       |                            | Delete instruction   |
| GET    | /api/instructions/sync-check |                            | Memory sync report   |
| POST   | /api/instructions/sync       |                            | Sync memory → DB     |

#### /api/activity-logs
| Method | Path                    | Query Params                        | Purpose        |
|--------|-------------------------|-------------------------------------|----------------|
| GET    | /api/activity-logs      | project_id, agent_id, entity_type, limit | List logs |
| GET    | /api/activity-logs/{id} |                                     | Get log        |
| POST   | /api/activity-logs      |                                     | Create log     |

#### /api/test-results
| Method | Path                        | Query Params                  | Purpose              |
|--------|-----------------------------|-------------------------------|----------------------|
| GET    | /api/test-results           | project_id, suite, status, limit | List results      |
| GET    | /api/test-results/performance| project_id, limit            | Lightweight history  |
| GET    | /api/test-results/{id}      |                               | Get result           |
| POST   | /api/test-results           |                               | Create result        |

#### /api/failure-records
| Method | Path                         | Query Params                                            | Purpose            |
|--------|------------------------------|---------------------------------------------------------|--------------------|
| GET    | /api/failure-records         | project_id, sprint_id, agent_id, failure_type, resolved | List records       |
| GET    | /api/failure-records/summary | project_id                                              | Aggregated analysis|
| GET    | /api/failure-records/{id}    |                                                         | Get record         |
| POST   | /api/failure-records         |                                                         | Create record      |
| PATCH  | /api/failure-records/{id}    |                                                         | Update record      |
| DELETE | /api/failure-records/{id}    |                                                         | Delete record      |

#### /api/tokens
| Method | Path              | Purpose                                          |
|--------|-------------------|--------------------------------------------------|
| GET    | /api/tokens/audit | Token audit: totals, by-agent, by-project, discrepancies |

#### /api/status
| Method | Path                      | Purpose                                    |
|--------|---------------------------|--------------------------------------------|
| GET    | /api/status               | Health check + active counts               |
| GET    | /api/status/test-coverage | Router test coverage report                |
| GET    | /api/status/code-standards| Code header format template                |

#### /api/playbooks
| Method | Path                                   | Purpose                        |
|--------|----------------------------------------|--------------------------------|
| GET    | /api/playbooks                         | List available playbooks       |

---

## 4. Frontend

### Stack

- **React 18** with React Router 6 for routing
- **Zustand** for state management
- **Vite** for dev server and bundling
- **Plain CSS** with custom properties (no frameworks)

### Route Map

```
/                                    → DashboardPage
/projects/:id                        → ProjectPage
/projects/:id/tickets                → TicketsPage
/projects/:id/tickets/:ticketId      → TicketDetailPage
/projects/:id/sprints/:sprintId      → SprintPage
/projects/:id/epics/:epicId          → EpicPage
/projects/:id/agents                 → ProjectAgentsPage
/projects/:id/agents/:agentId        → AgentPage
/projects/:id/tests                  → ProjectTestsPage
/instructions                        → InstructionsPage
/tests                               → TestResultsPage
/tests/:runId                        → TestResultsPage (detail mode)
```

### Key UI Features

- **Status history timeline** on ticket detail pages — shows every status transition with timestamps
- **Failure record review form** — PM can update failure_type, notes, root_cause, resolution, mark resolved
- **Test performance tab** — duration charts, drill-down to individual tests, average/diff metrics
- **Test count sparklines** — inline pass/fail trends on project and sprint views
- **Token scan button** — triggers POST /api/projects/:id/scan-tokens from the UI
- **Adaptive polling** — 2s when active, 10s when idle

### Zustand Store

Single store at `src/store/useStore.js` holds all application state:

**Data slices:** projects, sprints, epics, agents, projectAgents, tickets, comments, alerts, instructions, activityLog, testRuns, failureRecords

**Selectors:** `getProject(id)`, `getSprint(id)`, `getTicketsByProject(id)`, `getTicketsByAgent(id)`, `getAgentsByProject(id)` (resolves via join table), `getOpenAlerts()`, `getDashboard()` (aggregated metrics)

**Polling state:** interval (2000ms or 10000ms), isActive flag, lastUpdated timestamp

### CSS Architecture

Plain CSS with custom properties. No frameworks, no CSS-in-JS.

| File          | Purpose                                               |
|---------------|-------------------------------------------------------|
| theme.css     | Custom properties (colors, fonts), global resets      |
| layout.css    | AppShell grid, sidebar, header, footer                |
| common.css    | StatusBadge, AlertBanner, DataTable, buttons          |
| dashboard.css | Project cards, summaries, token displays              |
| agents.css    | Agent cards and detail pages                          |
| tickets.css   | Ticket lists, detail, comments, filters, timeline     |
| charts.css    | AsciiChart, AsciiProgressBar, SprintVelocity          |
| tests.css     | Test run listings, detail views, sparklines           |

Font: JetBrains Mono / Fira Code (monospace). BEM-inspired naming (`component__element`, `component--variant`).

---

## 5. Scripts and Hooks

All scripts in `backend/scripts/`. All env vars are optional with sensible defaults.

### run_tests.sh

Runs the pytest suite and optionally POSTs results to the API.

```
./scripts/run_tests.sh                                    # run only
./scripts/run_tests.sh --post --project-id 1              # run + POST
./scripts/run_tests.sh --post --project-id 1 --triggered-by "agent:tester"
./scripts/run_tests.sh --post --project-id 1 --context "after sprint close"
```

Activates venv automatically, loads `.env` for DB settings. Uses `pytest-json-report` for structured output. Per-test durations computed by summing setup + call + teardown phase durations. POST payload matches `TestResultCreate` schema. Failed test results auto-create failure_records.

### attribute_tokens.py

Scans Claude Code transcript JSONL files and attributes tokens to tickets.

```
python scripts/attribute_tokens.py                         # scan + attribute
python scripts/attribute_tokens.py --dry-run               # scan only
python scripts/attribute_tokens.py --project-id 1          # specific project
python scripts/attribute_tokens.py --force                  # re-process all
```

Workflow:
1. Finds transcript dirs under `~/.claude/projects/` matching `local_agent_tracker`
2. For each JSONL file: reads agentName, counts tokens, resolves agent ID
3. Skips overhead roles (team-lead, pm) and already-attributed sessions
4. Finds agent's in_progress/todo ticket and POSTs tokens
5. Outputs JSON summary on last line (consumed by API endpoint and shell wrapper)

State file (`/tmp/lat_token_attribution_state.json`) tracks attributed sessions. Always exits 0.

### run_token_scan.sh

Shell wrapper for `attribute_tokens.py`. Parses args, activates venv, loads .env, runs the scanner, and posts a summary alert to the API.

```
./scripts/run_token_scan.sh --project-id 1
./scripts/run_token_scan.sh --project-id 1 --dry-run
```

### report_tokens.py

Claude Code hook script for real-time token tracking. Reads hook event JSON from stdin, parses transcript JSONL for token counts, POSTs to the API.

Hook event types: `Stop`, `SubagentStop`, `TeammateIdle`.

Delta tracking via state file prevents double-counting. Always exits 0. On failure, posts an info alert.

### sync_instructions.py

Bidirectional sync between DB instructions and `docs/rules/` markdown files.

```
python scripts/sync_instructions.py              # report status
python scripts/sync_instructions.py --export     # DB → files
python scripts/sync_instructions.py --import     # files → DB
```

---

## 6. Testing Infrastructure

### Backend (pytest)

**Test database:** Separate `lat_test` database. Tables created once per session, dropped after. Each test gets a rolled-back transaction for isolation.

**Fixtures** (`conftest.py`):
- `create_tables` (session) — DDL setup/teardown
- `db_session` (function, auto-use) — transaction isolation, overrides `get_db`
- `client` — FastAPI TestClient
- Factory fixtures: `make_project`, `make_agent`, `make_epic`, `make_sprint`, `make_ticket`, `make_test_result`, `make_instruction`, `make_project_agent`

**Running tests:**
```bash
cd backend && source .venv/bin/activate
python -m pytest tests/ -v                    # run all
./scripts/run_tests.sh --post --project-id 1  # run + record to API
```

### Frontend (Vitest)

- Environment: jsdom
- Libraries: @testing-library/react, @testing-library/jest-dom
- Config: `frontend/vitest.config.js`

**Running tests:**
```bash
cd frontend
npm test          # single run
npm run test:watch # watch mode
```

---

## 7. Deployment

### Docker Compose

```yaml
services:
  mysql:        # lat_mysql — MySQL 8.0
    port: ${MYSQL_PORT:-3306}:3306   # .env sets 23847
    volumes: mysql_data:/var/lib/mysql
    healthcheck: mysqladmin ping

  phpmyadmin:   # lat_phpmyadmin
    port: ${PMA_PORT:-8080}:80
    depends_on: mysql (service_healthy)
```

### Startup Sequence

```
1. docker compose up -d          # Start MySQL + phpMyAdmin
2. cd backend && source .venv/bin/activate
3. alembic upgrade head          # Run migrations
4. uvicorn app.main:app          # Start API (port 8000)
5. cd frontend && npm run dev    # Start Vite (port 5173)
```

### Database Migrations

Alembic manages schema changes.

```bash
cd backend && source .venv/bin/activate
alembic upgrade head       # apply all
alembic revision -m "..."  # create new
alembic downgrade -1       # rollback one
```

---

## 8. Key Business Logic

### Sprint Completion Gates
Projects enforce up to 6 gates via `force_test_run`, `force_test_coverage`, `force_initial_md`, `force_architecture_md`, `force_headers` flags, plus unreviewed failure records check. Sprint service validates these before allowing status → completed.

### Auto-Assignment
- Ticket `sprint_id` auto-assigned to the project's active sprint on creation
- Ticket `epic_id` inherited from sprint's epic
- Sprint `name` auto-generated from goal if omitted or generic

### Status History and Time Tracking
- Every ticket status change records a `status_history` entry
- `time_spent_seconds` auto-computed: sum of all in_progress intervals from history
- Rework detection: in_progress after done creates failure_record + PM alert

### Token Tracking
- Per-ticket: `POST /api/tickets/{id}/tokens` increments `tokens_used`, `time_spent_seconds`, sets `token_source`
- Per-project overhead: `POST /api/projects/{id}/overhead` increments `tl_overhead_tokens` or `pm_overhead_tokens`
- Transcript scan: `POST /api/projects/{id}/scan-tokens` runs attribute_tokens.py
- Auto-scan on sprint close
- Audit: `GET /api/tokens/audit` cross-checks totals and flags discrepancies
- Attribution detail: `GET /api/tickets/{id}/token-attribution`

### Alert Auto-Creation
- Ticket marked done with 0 tokens → info alert
- Sprint completed → alerts for team-lead, pm, tester + auto-creates test ticket
- Doc gate failing → critical alert for TL
- Token scan success/failure → info/warning alert
- Rework detected → info alert for PM

### Failure Analysis
- Manual records: A-G taxonomy
- Auto-detected: rework (from status_history), test_failure (from test results)
- Sprint gate: unreviewed stubs block close
- Summary endpoint: aggregated by type, agent, sprint, trend

### Project Deletion Cascade
Deleting a project cascades through: alerts, test_results, activity_logs, instructions, tickets (and their comments, status_history), failure_records, project_agents, sprints, epics.
