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

24 model files in `app/models/`. See individual model files for full column definitions.

| Table | Key Columns | Notes |
|-------|-------------|-------|
| **projects** | prefix, name, status, repo_path, jira_base_url, jira_project_key, tl/pm_overhead_tokens, tl/pm_overhead_time_seconds, force_headers, force_test_coverage, force_test_run, force_initial_md, force_architecture_md, force_handoff_md, force_consolidation, playbooks_deployed_at | 7 sprint gate flags, all default OFF (opt-in). Status: active/paused/completed/archived |
| **epics** | project_id, name, description, status | Status: open/in_progress/completed |
| **sprints** | project_id, epic_id, name, goal, sprint_number, status, start/end_date | Name auto-generated from goal. Completion triggers gate validation + alerts |
| **tickets** | project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, jira_issue_key, title, description, ticket_type, status, tokens_used, time_spent_seconds, token_source, completed_at | Auto-assigns sprint/epic on create. Status change triggers history + tracking events |
| **agents** | project_id, name, description, role, api_key, is_active | role maps to Claude teammate name. **Per-project rows** (DWB-287, 2026-06-03): every agent belongs to exactly one project; same Claude teammate name on two projects = two agent rows. **Globally unique name** (DWB-315, 2026-06-05): `UNIQUE(name)` system-wide. Fixed-role agents that recur on every project are suffixed with `_<PROJECT_PREFIX>` (e.g., `Archie_DWB`, `Pam_DWB`); the identify endpoint accepts either form. Workers without cross-project collisions keep their plain name. |
| **project_agents** | project_id, agent_id, assigned_at | Unique constraint: (project_id, agent_id). Agents are 1:1 with a single project (see agents table); this table additionally tracks assigned-at timestamps for active-roster queries. |
| **tracking_log** | ticket_id, agent_id, project_id, sprint_id, event_type, tokens, timestamp, source | event_type: start/stop/token_report/overhead_start/overhead_stop |
| **status_history** | ticket_id, old_status, new_status, changed_at, changed_by_agent_id | Used for time computation + rework detection |
| **failure_records** | project_id, ticket_id, sprint_id, agent_id, logged_by_agent_id, failure_type, severity, attempt_number, notes, root_cause, resolution, resolved | Two FK to agents. Unreviewed stubs block sprint close |
| **comments** | ticket_id, author_agent_id, body, created_at | |
| **alerts** | project_id, raised_by_agent_id, ticket_id, title, body, severity, status, created_at, resolved_at, user_sent_at, recipient_agent_id | Severity: info/warning/critical. Status: open/acknowledged/resolved. `recipient_agent_id` (DWB-426) targets a per-agent broadcast (e.g. scoring carrot/stick); null = project-wide |
| **tool_actions** | agent_id, session_id, dwb_session_id, ticket_id, tool_name, target, event_type, tool_metadata, created_at | DWB-417: one row per captured agent action (PostToolUse / lifecycle hook). Context resolved from `session_id` like session-end attribution; all FKs nullable (delivery-gap tolerant). event_type: file_written/message_sent/agent_spawned/notification/context_compaction |
| **score_event** | project_id, sprint_id, subject_agent_id, delta, source, trigger_type, actor_agent_id, actor_cost, reason, ref_type/ref_id, reverted_by, created_at | DWB-424 append-only scoring ledger (source of truth). source: auto/human/peer. Corrections append a reverting row; rows are never deleted |
| **agent_score** | (agent_id, project_id) PK, reputation, influence, updated_at | DWB-424 derived cache, rebuildable from score_event. `reputation` = all-time rank; `influence` = per-sprint peer budget (ledger-derived, auto-resets) |
| **tl_messages** | from_agent_id, to_agent_id (NULL=broadcast), from_project_id, body, created_at | DWB-436 cross-project team-lead channel. NOT project-scoped; from_project_id only records the sender's home project |
| **tl_message_reads** | (message_id, agent_id) PK, read_at | DWB-436 per-(message, agent) read receipt; message_id FK ON DELETE CASCADE |
| **instructions** | scope, project_id, agent_id, title, body | Scope: global/project/agent |
| **activity_log** | project_id, agent_id, entity_type, entity_id, action, details, created_at | Auto-populated by middleware |
| **test_results** | project_id, sprint_id, ticket_id, run_at, suite, total_tests, passed, failed, skipped, duration_seconds, status, details, triggered_by, triggered_context | Failed results auto-create failure_records |
| **hook_sessions** | session_id, transcript_path, agent_id, project_id, ticket_id, sprint_id, start_time, end_time, total_tokens, token_breakdown, status, session_type, agent_name, hook_event, created_at | Status: active/completed/error. Type: main/teammate/subagent |
| **error_logs** | project_id, agent_id, source, endpoint, error_type, message, stack_trace, file_path, function_name, line_number, status_code, created_at | Source: backend/frontend/hook |
| **failed_hooks** | session_id, hook_event, reason, cwd, agent_type, agent_name, agent_id_from_marker, project_id, hook_data, created_at | DWB-288 audit table for marker-resolution failures. Every `resolve_agent_from_marker` miss writes a row with the failure reason (`marker_missing`, `marker_unparseable`, `marker_agent_not_found`, etc.) and the raw hook payload, so the diagnostic isn't silent. |

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

- **Routers** (`app/routers/`): Define endpoints, validate input via Pydantic, inject DB session via `Depends(get_db)`. 23 router files.
- **Services** (`app/services/`): Business logic, cross-entity operations, auto-triggers (status history, rework detection, time computation, failure records, token attribution, tracking events, action capture, scoring, demo seeding). 32 service files.
- **Models** (`app/models/`): SQLAlchemy 2.0 ORM classes with Mapped types and relationships. 18 model files.
- **Schemas** (`app/schemas/`): Pydantic v2 models with ConfigDict(from_attributes=True) for Create, Update, Read per entity. List endpoints use slim schemas that strip heavy fields (e.g., `TestResultListRead` omits `details`, `AgentListRead` omits `api_key`). Tickets, alerts, and sprints support `?fields=slim` for minimal payloads.
- **Middleware** (`app/middleware/`): ActivityLoggerMiddleware auto-logs all mutations.

### ActivityLoggerMiddleware

Intercepts all POST/PATCH/PUT/DELETE requests with 2xx responses and inserts an `activity_log` row.

Agent ID resolution priority: (1) `X-Agent-ID` header, (2) entity fields (`raised_by_agent_id`, `assigned_agent_id`), (3) generic body (`agent_id`, `author_agent_id`), (4) project PM/TL fallback for sprint/epic creation, (5) null (shows as "system").

Disabled during testing (`TESTING=1` env var).

### Endpoint Reference

Full interactive reference at http://localhost:8000/docs (OpenAPI): 138 endpoints across 23 routers, standard CRUD per resource. The non-obvious / automation endpoints are catalogued in `README.md` API Reference. Notes that matter for the data model:

- `GET /api/projects/{id}/team` (single-roundtrip roster) returns `{project_id, project_prefix, agents: [{agent_id, name, role, is_active, assigned_at, last_seen, presumed_live}]}`, active-only unless `?include_inactive=true`.
- `GET /api/tracking/summary` `per_agent` rows aggregate `token_report` + `overhead_token_report` (a `tokens` total plus a separate `overhead_tokens`); `project_total.overhead_tokens` is the project-wide overhead figure.
- `POST /api/agents/identify` + `/spawn-prepare` resolve `(role, name, project_prefix)`, accepting the short name or `<name>_<PREFIX>` form.
- Agent memory (DWB-401) lives at `<repo>/.dwb/memory/<prefix>/<name>/` (outside the protected `.claude/` tree so subagents write it directly): `identity.md` (system-generated) + a free-form `memory.md` (agent-written, merges the old scratchpad + lessons; `recent_sessions` dropped, the DB is the session index). Writes via `memory/append` (`file=memory`) + `session-complete`. `memory.md` has a 4500-token passive trim ceiling (drop-oldest, never a close gate).
- `GET /api/hooks/sessions?status=orphan&cutoff_minutes=60` returns stale active sessions for cleanup.
- DWB session lifecycle: `POST /api/sessions/open` (omit `opened_at`), `.../close` (headline required on ai_confident/ai_asked; consolidation gate opt-in via `force_consolidation`, default OFF, TL-owned docs only), `.../reopen` (undoes a false close; 409 if another is open).
- DWB session detection (DWB-402, Layer-2 Haiku retired): Layer-1 regex on open/close phrases, a SessionEnd transcript scan, slash commands (`/dwb-open`, `/dwb-close`), a 60-min idle sweeper. `ai_classifier` enum kept as a tombstone. Full reference: `docs/session_lifecycle.md`.
- Action capture (DWB-417/421): `POST /api/hooks/tool-use` (matcher-scoped PostToolUse) and `POST /api/hooks/lifecycle-event` (Notification / PreCompact) are fire-and-forget, always return 200, and write `tool_actions` rows.
- Scoring (epic 28): `GET /api/projects/{id}/scores` (leaderboard), `GET /api/agents/{id}/score` and `GET .../scores/agent?agent=NAME` (detail + reasoned ledger), `POST .../scores/award` (human), `POST .../scores/peer` (peer, `X-Agent-ID` header), `POST .../scores/rebuild`. See § 8.
- Team-lead channel (DWB-436/437): `GET /api/tl-channel` (whole channel, cross-project; each message carries a `read_by` roster), `GET /api/tl-channel/unread?agent_id=`, `POST /api/tl-channel` (send, role-guarded), `POST /api/tl-channel/mark-read`. See § 8.

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
| PostToolUse | POST /api/hooks/tool-use | Captures Write/Edit/MultiEdit/NotebookEdit/Task/SendMessage actions (DWB-417) |
| Notification | POST /api/hooks/lifecycle-event | `notification` event_type (DWB-421) |
| PreCompact | POST /api/hooks/lifecycle-event | `context_compaction` event_type (DWB-421) |

The capture endpoints are fire-and-forget (always 200). Hook config lives in `.claude/settings.json` and the canonical `_HOOKS_SETTINGS_BLOCK` in `routers/playbooks.py`, kept in sync by a drift guard.

**SubagentStop field mapping** (sends different field names than SessionEnd):

| SubagentStop field | SessionEnd field | Purpose |
|---|---|---|
| `hook_event_name` | `hook_event` | Event type identifier |
| `agent_type` | `agent_name` | Teammate role/name |
| `agent_id` | `session_id` | Unique session key |
| `agent_transcript_path` | `transcript_path` | Path to JSONL transcript |

SubagentStop creates a separate HookSession keyed on `agent_id` (not the parent `session_id`). Unmatched agent types (e.g. "Explore" subagent) fall back to TL as overhead.

**SubagentStop transcript fallback (DWB-311).** CC's SubagentStop sends a synthetic `agent_transcript_path` that doesn't exist on disk; the real transcript is interleaved in the parent session's `.jsonl`, each line tagged `agentName`. When `parse_transcript()` returns 0, `_handle_subagent_stop()` falls back to `_parse_subagent_from_projects_dir`: sum usage from lines where `agentName == agent.name`. It runs only when the primary parse misses, the synthetic file is absent, and the marker resolved a named agent; on failure it returns zero, never worsening attribution.

**Marker-based attribution (DWB-294, 304).** SubagentStop session_ids are CC-internal and can't be pre-computed. The TL writes a **pending marker** at spawn: `.claude/agents/active/pending-<agent_id>-<unix_ms>-<rand4hex>` (JSON dict). On `_handle_subagent_stop`, `resolve_agent_from_marker` tries a literal `.claude/agents/active/<session_id>` lookup, else **atomically renames** the oldest unconsumed `pending-*` marker for the project to `<session_id>` (consumed once). Failures (missing/unparseable marker, unresolved agent_id) write a `failed_hooks` row with a specific `reason`.

**Marker file format** (all marker files, both literal and pending, are JSON dicts):

```json
{"agent_id": 21, "agent_name": "Barry_DWB", "role": "backend-worker", "project_prefix": "DWB"}
```

`agent_id` is the only authoritative field for attribution; the others are convenience/diagnostic.

Workers get tokens on their active ticket (in_progress/in_review/recently-done ~5min); TL/PM get project overhead (`tl_overhead_tokens`/`pm_overhead_tokens`, DWB-305). Key files: `hook_tracking.py` (logic incl marker resolution + projects-dir fallback), `routers/hooks.py` (4 endpoints, never 5xx; failures -> `failed_hooks` + `error_logs`), `models/hook_session.py`, `models/failed_hook.py`.

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
Projects enforce up to 7 gates via `force_test_run`, `force_test_coverage`, `force_initial_md`, `force_architecture_md`, `force_handoff_md`, `force_headers`, `force_consolidation` flags, plus unreviewed failure records check. Sprint service validates these before allowing status -> completed. All gate flags default OFF (opt-in per project). `force_headers` enforces the standard code-header block on sprint-touched `.py` files only (surfaced in `GET /gate-status`, with a token-cost warning in the UI when ON). `force_consolidation` counts only TL-owned shipped docs toward the consolidation/compaction gate; agent memory is gate-exempt.

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
- **Primary (passive):** lifecycle hooks capture tokens/time (§5); they increment `ticket.tokens_used` and the project overhead fields directly. Worker priority: `in_progress` > `todo` > `in_review` > recently `done` (5 min).
- **Per-ticket via tracking API:** `POST /api/tracking/tokens` inserts event + increments ticket
- **Per-ticket legacy:** `POST /api/tickets/{id}/tokens` increments directly (also inserts tracking event)
- **Per-project overhead:** `POST /api/projects/{id}/overhead` increments `tl_overhead_tokens` or `pm_overhead_tokens`
- **Audit:** `GET /api/tokens/audit` cross-checks totals and flags discrepancies
- **Attribution detail:** `GET /api/tickets/{id}/token-attribution`
- **Project summary:** `GET /api/tracking/summary` — per-ticket, per-agent, per-sprint rollups

### Deterministic Action Capture
CC hooks capture actions passively (DWB-417..421): `PostToolUse` -> `/api/hooks/tool-use`, `Notification`/`PreCompact` -> `/api/hooks/lifecycle-event`. Each `tool_actions` row classifies an `event_type` and emits a feed verb; `message_sent` records the recipient only, never the body. Context resolves from `session_id` like session-end; all FKs nullable so a delivery gap never drops the row.

### Agent Scoring
Per-agent-per-project scoring (epic 28, DWB-424..428). Append-only `score_event` ledger = source of truth; `agent_score` = rebuildable cache. Two currencies: **reputation** (all-time rank) and **influence** (per-sprint peer budget, default 20, ledger-derived, auto-resets). Values + caps in `app/config/scoring.py`.
- **Auto-triggers** (no agent action): ticket_closed (+ no-rework bonus), rework, test_failure, stale, zero_token_close, gate_miss, forgot. Attributed via `ticket.assigned_agent_id` / `failure_record.logged_by`, not session attribution, so the right worker is credited.
- **Human tools** (free): `/carrot` `/stick` `/score` `/leaderboard` -> `POST .../scores/award`.
- **Peer economy:** `POST .../scores/peer` (`X-Agent-ID` header). Flat - any agent may carrot/stick any other; only self-scoring is barred. Caps + the 20 influence/sprint budget in `config/scoring.py`.
- **Broadcast:** human + peer carrot/sticks notify all project agents via per-agent alerts (`alert.recipient_agent_id`); human critical, peer info. Auto-triggers do not broadcast.

### Archie Channel (Cross-Project TL Messaging)
`tl_messages` (DWB-436/437) is a cross-project channel for team-leads. A message is direct (`to_agent_id` set) or broadcast (`to_agent_id` NULL = all other TLs); every TL can read every message, and `tl_message_reads` tracks per-(message, agent) read state. Role guard: the sender and any named recipient must be `role=team-lead`, else 400. Ping: a direct send writes one alert to the target, a broadcast one per OTHER active team-lead (reusing `alert.recipient_agent_id`), each landing on the recipient's project board. On spawn, an archie's unread messages render atop its `identity.md` (in `scaffold_agent_dir`, beside the scoring standing block) and are marked read once shown; `/tl` is the reply path. The table is NOT project-scoped; `delete_project` clears messages sent from the deleted project.

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
