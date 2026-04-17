# Architecture

Technical reference for D'Waantu B'Guantu (DWB).

```
+-------------------------------------------------------------+
|                    D'Waantu B'Guantu                         |
|                                                              |
|  +----------+    +------------------+    +---------------+   |
|  |  React    |--->|  FastAPI         |--->|  MySQL 8.0    |   |
|  |  :5173    |<---|  :8000           |<---|  :23847       |   |
|  +----------+    +------------------+    +---------------+   |
|       |               ^       ^                ^             |
|       |               |       |                |             |
|       |          +-------+ +--------------+ +----------+    |
|       |          |Claude | |Activity Logger| |phpMyAdmin |    |
|       |          |Code   | | (middleware)  | |  :8080    |    |
|       |          |Hooks  | +--------------+ +----------+    |
|       |          +-------+                                   |
|       |            |  SessionStart  -> POST /api/hooks/...   |
|  Vite dev server   |  SessionEnd   -> parse transcript JSONL |
|  polls /api/status |  SubagentStop -> dedicated handler      |
|  adaptive 2s/10s   |                                         |
|                    Docker Compose manages DB + PMA            |
+-------------------------------------------------------------+
```

---

## 1. System Overview

Three-tier architecture for tracking AI agent work across projects, sprints, and tickets.

| Layer      | Technology           | Port  | Purpose                          |
|------------|----------------------|-------|----------------------------------|
| Frontend   | React 18 + Vite      | 5173  | Dashboard, project management UI |
| Backend    | FastAPI + SQLAlchemy  | 8000  | REST API, business logic         |
| Database   | MySQL 8.0 (Docker)   | 23847 | Persistent storage               |
| Admin      | phpMyAdmin (Docker)   | 8080  | DB administration                |
| Middleware | ActivityLoggerMiddleware | --  | Auto-logs all mutations          |

The frontend polls the backend with adaptive intervals (2s when agents are active, 10s when idle). The backend follows a router -> service -> model pattern. An activity logger middleware auto-records all POST/PATCH/DELETE operations.

---

## 2. Data Model

### Entity Hierarchy

```
Project
+-- Epic
|   +-- (tickets grouped by epic)
+-- Sprint
|   +-- Ticket
|       +-- StatusHistory (every status transition)
|       +-- TrackingLog (start/stop/token events)
|       +-- HookSession (passive tracking sessions)
|       +-- Comment
|       +-- FailureRecord (optional)
|       +-- TestResult (optional)
|       +-- Alert (optional)
+-- ProjectAgent (join table)
+-- HookSession (passive tracking)
+-- Instruction (scoped)
+-- ActivityLog (auto-populated by middleware)
+-- TrackingLog (time/token events)
+-- TestResult
+-- FailureRecord (project-level)
+-- Alert (project-level)
+-- ErrorLog (system-wide error tracking)

Agent (standalone)
+-- ProjectAgent (assigned to projects)
+-- Ticket (assigned work)
+-- TrackingLog (time/token events)
+-- Comment (authored)
+-- Alert (raised)
+-- FailureRecord (agent + logged_by_agent)
+-- StatusHistory (changed_by_agent)
+-- Instruction (scoped to agent)
```

### Tables

16 model files in `app/models/`. See individual model files for full column definitions.

| Table | Key Columns | Notes |
|-------|-------------|-------|
| **projects** | prefix, name, status, repo_path, jira_base_url, jira_project_key, tl/pm_overhead_tokens, tl/pm_overhead_time_seconds, force_headers, force_test_coverage, force_test_run, force_initial_md, force_architecture_md, force_team_md, force_handoff_md, playbooks_deployed_at | 8 sprint gate flags. Status: active/paused/completed/archived |
| **epics** | project_id, name, description, status | Status: open/in_progress/completed |
| **sprints** | project_id, epic_id, name, goal, sprint_number, status, start/end_date | Name auto-generated from goal. Completion triggers gate validation + alerts |
| **tickets** | project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, jira_issue_key, title, description, ticket_type, status, tokens_used, time_spent_seconds, token_source, completed_at | Auto-assigns sprint/epic on create. Status change triggers history + tracking events |
| **agents** | name, description, role, api_key, is_active | role maps to Claude teammate name |
| **project_agents** | project_id, agent_id, assigned_at | Unique constraint: (project_id, agent_id) |
| **tracking_log** | ticket_id, agent_id, project_id, sprint_id, event_type, tokens, timestamp, source | event_type: start/stop/token_report/overhead_start/overhead_stop |
| **status_history** | ticket_id, old_status, new_status, changed_at, changed_by_agent_id | Used for time computation + rework detection |
| **failure_records** | project_id, ticket_id, sprint_id, agent_id, logged_by_agent_id, failure_type, severity, attempt_number, notes, root_cause, resolution, resolved | Two FK to agents. Unreviewed stubs block sprint close |
| **comments** | ticket_id, author_agent_id, body, created_at | |
| **alerts** | project_id, raised_by_agent_id, ticket_id, title, body, severity, status, created_at, resolved_at, user_sent_at | Severity: info/warning/critical. Status: open/acknowledged/resolved |
| **instructions** | scope, project_id, agent_id, title, body | Scope: global/project/agent |
| **activity_log** | project_id, agent_id, entity_type, entity_id, action, details, created_at | Auto-populated by middleware |
| **test_results** | project_id, sprint_id, ticket_id, run_at, suite, total_tests, passed, failed, skipped, duration_seconds, status, details, triggered_by, triggered_context | Failed results auto-create failure_records |
| **hook_sessions** | session_id, transcript_path, agent_id, project_id, ticket_id, sprint_id, start_time, end_time, total_tokens, token_breakdown, status, session_type, agent_name, hook_event, created_at | Status: active/completed/error. Type: main/teammate/subagent |
| **error_logs** | project_id, agent_id, source, endpoint, error_type, message, stack_trace, file_path, function_name, line_number, status_code, created_at | Source: backend/frontend/hook |

---

## 3. API Layer

### Pattern: Router -> Service -> Model

```
Request -> ActivityLoggerMiddleware -> Router -> Service -> Model -> DB
              |                        |         |
              |                  Pydantic    SQLAlchemy
              |                  schemas     queries
              v
         activity_log table
         (auto-populated)
```

- **Routers** (`app/routers/`): Define endpoints, validate input via Pydantic, inject DB session via `Depends(get_db)`. 18 router files.
- **Services** (`app/services/`): Business logic, cross-entity operations, auto-triggers (status history, rework detection, time computation, failure records, token attribution, tracking events, demo seeding). 16 service files.
- **Models** (`app/models/`): SQLAlchemy 2.0 ORM classes with Mapped types and relationships. 16 model files.
- **Schemas** (`app/schemas/`): Pydantic v2 models with ConfigDict(from_attributes=True) for Create, Update, Read per entity.
- **Middleware** (`app/middleware/`): ActivityLoggerMiddleware auto-logs all mutations.

### ActivityLoggerMiddleware

Intercepts all POST/PATCH/PUT/DELETE requests with 2xx responses and inserts an `activity_log` row.

Agent ID resolution priority:
1. `X-Agent-ID` header (highest priority)
2. Response body entity-specific fields (`raised_by_agent_id` for alerts, `assigned_agent_id` for tickets)
3. Generic body fields (`agent_id`, `author_agent_id`)
4. Project PM/TL fallback for sprint/epic creation
5. null (shows as "system")

Disabled during testing (`TESTING=1` env var).

### Endpoint Reference

#### /api/projects
| Method | Path                                  | Query Params         | Purpose                    |
|--------|---------------------------------------|----------------------|----------------------------|
| GET    | /api/projects                         | status               | List projects              |
| GET    | /api/projects/{id}                    |                      | Get project                |
| POST   | /api/projects                         |                      | Create project             |
| POST   | /api/projects/from-repo               |                      | Create from repo scan      |
| POST   | /api/projects/seed-demo               |                      | Seed demo project          |
| PATCH  | /api/projects/{id}                    |                      | Update project             |
| POST   | /api/projects/{id}/overhead           |                      | Increment overhead tokens  |
| POST   | /api/projects/{id}/disable-jira       |                      | Clear all Jira links       |
| DELETE | /api/projects/{id}                    |                      | Delete (cascades all)      |
| GET    | /api/projects/{id}/gate-status        |                      | Check sprint gates         |
| GET    | /api/projects/{id}/tests              | suite, status, limit | Project test runs          |
| GET    | /api/projects/{id}/docs               |                      | Read project doc files     |
| GET    | /api/projects/{id}/playbook-files     |                      | List playbook files in .claude/ |
| GET    | /api/projects/{id}/activity-feed      | limit                | Activity log with agents   |

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
| Method | Path                               | Query Params                                                          | Purpose             |
|--------|------------------------------------|-----------------------------------------------------------------|---------------------|
| GET    | /api/tickets                       | project_id, sprint_id, epic_id, assigned_agent_id, status, ticket_type | List tickets        |
| POST   | /api/tickets/stale-check           |                                                                 | Deduped stale alert |
| GET    | /api/tickets/{id}                  |                                                                 | Get ticket          |
| POST   | /api/tickets                       |                                                                 | Create ticket       |
| PATCH  | /api/tickets/{id}                  |                                                                 | Update ticket       |
| GET    | /api/tickets/{id}/history          |                                                                 | Status history      |
| GET    | /api/tickets/{id}/token-attribution|                                                                 | Token breakdown     |
| POST   | /api/tickets/{id}/tokens           |                                                                 | Increment tokens    |
| DELETE | /api/tickets/{id}                  |                                                                 | Delete ticket       |

#### /api/tracking
| Method | Path                      | Purpose                                |
|--------|---------------------------|-----------------------------------------|
| POST   | /api/tracking/start       | Log work start (ticket_id, agent_id)    |
| POST   | /api/tracking/stop        | Log work stop (ticket_id, agent_id)     |
| POST   | /api/tracking/tokens      | Log token report (ticket_id, agent_id, tokens, source) |
| POST   | /api/tracking/overhead/start | Log overhead start (project_id, agent_id) |
| POST   | /api/tracking/overhead/stop  | Log overhead stop (project_id, agent_id)  |
| GET    | /api/tracking/summary     | Full rollup (per_ticket, per_agent, per_sprint, project_total) |

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
| POST   | /api/alerts/send-to-team| project_id (query)            | Write ALERTS_PENDING.md to repo |
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
| POST   | /api/instructions/sync       |                            | Sync memory -> DB    |

#### /api/activity-logs
| Method | Path                    | Query Params                        | Purpose        |
|--------|-------------------------|-------------------------------------|----------------|
| GET    | /api/activity-logs      | project_id, agent_id, entity_type, limit | List logs |
| GET    | /api/activity-logs/{id} |                                     | Get log        |
| POST   | /api/activity-logs      |                                     | Create log     |

#### /api/test-results
| Method | Path                         | Query Params                     | Purpose              |
|--------|------------------------------|----------------------------------|----------------------|
| GET    | /api/test-results            | project_id, suite, status, limit | List results         |
| GET    | /api/test-results/performance| project_id, limit                | Lightweight history  |
| GET    | /api/test-results/{id}       |                                  | Get result           |
| POST   | /api/test-results            |                                  | Create result        |

#### /api/failure-records
| Method | Path                         | Query Params                                            | Purpose            |
|--------|------------------------------|---------------------------------------------------------|--------------------|
| GET    | /api/failure-records         | project_id, sprint_id, agent_id, failure_type, resolved | List records       |
| GET    | /api/failure-records/summary | project_id                                              | Aggregated analysis|
| GET    | /api/failure-records/{id}    |                                                         | Get record         |
| POST   | /api/failure-records         |                                                         | Create record      |
| PATCH  | /api/failure-records/{id}    |                                                         | Update record      |
| DELETE | /api/failure-records/{id}    |                                                         | Delete record      |

#### /api/errors
| Method | Path           | Query Params                | Purpose           |
|--------|----------------|-----------------------------|--------------------|
| POST   | /api/errors    |                             | Create error log   |
| GET    | /api/errors    | project_id, source, limit   | List error logs    |

#### /api/hooks
| Method | Path                       | Query Params         | Purpose                        |
|--------|----------------------------|----------------------|--------------------------------|
| POST   | /api/hooks/session-start   |                      | Receive SessionStart hook data |
| POST   | /api/hooks/session-end     |                      | Receive SessionEnd/SubagentStop hook data |
| GET    | /api/hooks/sessions        | project_id, status   | List hook sessions             |
| GET    | /api/hooks/sessions/{id}   |                      | Get session by ID              |

#### /api/tokens
| Method | Path              | Purpose                                          |
|--------|-------------------|--------------------------------------------------|
| GET    | /api/tokens/audit | Token audit: totals, by-agent, by-project, discrepancies |

#### /api/status and /api/system
| Method | Path                       | Purpose                                    |
|--------|----------------------------|--------------------------------------------|
| GET    | /api/status                | Health check + active counts + infra warnings |
| GET    | /api/status/test-coverage  | Router test coverage report                |
| GET    | /api/status/code-standards | Code header format template                |
| GET    | /api/system/docs           | Read system docs (README, ARCHITECTURE)    |
| POST   | /api/system/run-tests      | Trigger backend test suite                 |

#### /api/playbooks
| Method | Path                                   | Purpose                        |
|--------|----------------------------------------|--------------------------------|
| GET    | /api/playbooks                         | List available playbooks       |
| POST   | /api/projects/{id}/deploy-playbooks    | Deploy playbooks + set timestamp |

---

## 4. Frontend

### Stack

- **React 18** with React Router 6 for routing
- **Zustand** for state management
- **Vite** for dev server and bundling
- **Plain CSS** with custom properties (no frameworks)

### Route Map

```
/                                    -> DashboardPage
/projects/:id                        -> ProjectPage
/projects/:id/tickets                -> TicketsPage
/projects/:id/tickets/:ticketId      -> TicketDetailPage
/projects/:id/sprints/:sprintId      -> SprintPage
/projects/:id/epics/:epicId          -> EpicPage
/projects/:id/agents                 -> ProjectAgentsPage (labeled "Team" in nav)
/projects/:id/agents/:agentId        -> AgentPage
/projects/:id/tests                  -> ProjectTestsPage
/projects/:id/docs                   -> DocsPage
/docs                                -> SystemDocsPage
/instructions                        -> InstructionsPage
/tests                               -> TestResultsPage
/tests/:runId                        -> TestResultsPage (detail mode)
/errors                              -> ErrorLogPage
```

### Key UI Features

- **Status history timeline** on ticket detail pages
- **Failure record review form** with type, notes, root_cause, resolution
- **Test performance tab** with duration charts and sparklines
- **TEAM.md panel** on the Team page (collapsible, read-only)
- **Tracking summary** with time/token rollups from hooks
- **Adaptive polling** 2s active, 10s idle

### API Client Layer

```
src/api/
+-- client.js          # fetch wrapper, ApiError class
+-- projects.js        # CRUD + deployPlaybooks
+-- sprints.js         # CRUD
+-- epics.js           # CRUD
+-- agents.js          # CRUD
+-- tickets.js         # CRUD
+-- comments.js        # Create, list, delete
+-- alerts.js          # CRUD + dismissAll + requestTestRun + sendToTeam
+-- instructions.js    # CRUD + syncCheck + sync + playbooks
+-- activityLogs.js    # Read-only
+-- projectAgents.js   # Read-only
+-- testResults.js     # Read by ID or project
+-- failureRecords.js  # CRUD
+-- tokens.js          # getTokenAudit()
+-- tracking.js        # getTrackingSummary(projectId)
+-- status.js          # getStatus, getTestCoverage, getCodeStandards
+-- system.js          # runSystemTests
+-- docs.js            # getProjectDocs, getSystemDocs
```

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

All scripts in `backend/scripts/`. Three files: `migrate.sh`, `run_tests.sh`, `sync_instructions.py`.

### run_tests.sh

Runs the pytest suite and optionally POSTs results to the API.

```
bash backend/scripts/run_tests.sh                                    # run only
bash backend/scripts/run_tests.sh --post --project-id 1              # run + POST
bash backend/scripts/run_tests.sh --post --project-id 1 --triggered-by "agent:tester"
bash backend/scripts/run_tests.sh --post --project-id 1 --context "after sprint close"
```

Activates venv automatically, loads `.env` for DB settings. Uses `pytest-json-report` for structured output. Per-test durations computed by summing setup + call + teardown phase durations. POST payload matches `TestResultCreate` schema. Failed test results auto-create failure_records.

### sync_instructions.py

Bidirectional sync between DB instructions and `docs/rules/` markdown files.

```
python scripts/sync_instructions.py              # report status
python scripts/sync_instructions.py --export     # DB -> files
python scripts/sync_instructions.py --import     # files -> DB
```

### Claude Code Lifecycle Hooks

Token and time attribution is handled passively by hooks configured in `.claude/settings.json`. No scripts to run.

**Hook events:**

| Event | Endpoint | Handler |
|-------|----------|---------|
| SessionStart | POST /api/hooks/session-start | `handle_session_start()` — creates HookSession(active), logs start |
| SessionEnd | POST /api/hooks/session-end | `handle_session_end()` — parses transcript, logs stop + tokens |
| SubagentStop | POST /api/hooks/session-end | Early-branch in `handle_session_end()` -> `_handle_subagent_stop()` |

**SubagentStop field mapping** (sends different field names than SessionEnd):

| SubagentStop field | SessionEnd field | Purpose |
|---|---|---|
| `hook_event_name` | `hook_event` | Event type identifier |
| `agent_type` | `agent_name` | Teammate role/name |
| `agent_id` | `session_id` | Unique session key |
| `agent_transcript_path` | `transcript_path` | Path to JSONL transcript |

SubagentStop creates a separate HookSession keyed on `agent_id` (not the parent `session_id`). Unmatched agent types (e.g. "Explore" subagent) fall back to TL as overhead.

Workers get tokens attributed to their active ticket (in_progress, in_review, or recently done). TL/PM get project overhead. Key files:
- `app/services/hook_tracking.py` — all business logic
- `app/routers/hooks.py` — 4 endpoints (never return 5xx)
- `app/models/hook_session.py` — session state model

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
python -m pytest tests/ -v                              # run all
bash scripts/run_tests.sh --post --project-id 1         # run + record to API
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
  mysql:        # lat_mysql -- MySQL 8.0
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
Projects enforce up to 8 gates via `force_test_run`, `force_test_coverage`, `force_initial_md`, `force_architecture_md`, `force_team_md`, `force_handoff_md`, `force_headers` flags, plus unreviewed failure records check. Sprint service validates these before allowing status -> completed.

### Auto-Assignment
- Ticket `sprint_id` auto-assigned to the project's active sprint on creation
- Ticket `epic_id` inherited from sprint's epic
- Sprint `name` auto-generated from goal if omitted or generic

### Status History and Time Tracking
- Every ticket status change records a `status_history` entry
- Status transitions auto-insert `tracking_log` start/stop events
- `time_spent_seconds` auto-computed: sum of all in_progress intervals from history
- Rework detection: in_progress after done creates failure_record + PM alert

### Token Tracking
- **Primary (passive):** Claude Code lifecycle hooks automatically capture tokens and time via `POST /api/hooks/session-start` and `POST /api/hooks/session-end`. Workers get tokens on their active ticket (in_progress, in_review, or recently done); TL/PM get overhead.
- **Per-ticket via tracking API:** `POST /api/tracking/tokens` inserts event + increments ticket
- **Per-ticket legacy:** `POST /api/tickets/{id}/tokens` increments directly (also inserts tracking event)
- **Per-project overhead:** `POST /api/projects/{id}/overhead` increments `tl_overhead_tokens` or `pm_overhead_tokens`
- **Audit:** `GET /api/tokens/audit` cross-checks totals and flags discrepancies
- **Attribution detail:** `GET /api/tickets/{id}/token-attribution`
- **Project summary:** `GET /api/tracking/summary` — per-ticket, per-agent, per-sprint rollups

### Alert Auto-Creation
- Ticket marked done with 0 tokens -> info alert
- Sprint completed -> alerts for team-lead, pm, tester + auto-creates test ticket
- Doc gate failing -> critical alert for TL
- Rework detected -> info alert for PM
- Unattributed hook session -> warning alert

### Stale Ticket Detection
`POST /api/tickets/stale-check` — PM polls for tickets stuck in_progress beyond a threshold. Creates a deduped warning alert (matches on ticket_key + minutes in title, only checks open/acknowledged). Resolves PM as alert raiser, falls back to assigned agent, then any project agent.

### ALERTS_PENDING.md Lifecycle
`POST /api/alerts/send-to-team?project_id=X` writes open alerts to `.claude/ALERTS_PENDING.md` in the project repo and tags each alert with `user_sent_at`. When all alerts for a project are resolved or dismissed, `_auto_unlink_alerts_file()` deletes the file automatically. Triggered after `dismiss_all()` and `update_alert()` status changes.

### Failure Analysis
- Manual records: A-G taxonomy (context_degradation, spec_drift, sycophantic_confirmation, tool_selection_error, cascading_failure, silent_failure, integration_failure)
- Auto-detected: rework (from status_history), test_failure (from test results)
- Sprint gate: unreviewed stubs block close
- Summary endpoint: aggregated by type, agent, sprint, trend

### Ticket Deletion Cascade
Deleting a ticket cascades through: comments, status_history, alerts, test_results, failure_records, tracking_log, hook_sessions — all via `ondelete=CASCADE` on FKs and `cascade="all, delete-orphan"` / `cascade="all, delete"` on relationships.

### Project Deletion Cascade
Deleting a project cascades through: alerts, test_results, activity_logs, instructions, tickets (and their children per above), failure_records, project_agents, sprints, epics.

### Jira Integration
Projects optionally link to a Jira project via `jira_project_key`. DWB tickets map 1:1 to Jira issues via `jira_issue_key` (unique constraint). `POST /api/projects/{id}/disable-jira` clears all Jira links from the project and its tickets. Jira data is never modified.
