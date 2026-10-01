# Architecture

Technical reference for D'Waantu B'Guantu (DWB).

```
React :5173  <->  FastAPI :8000  <->  MySQL 8.0 :23847  (+ phpMyAdmin :8080)
                        ^
   Claude Code hooks (SessionStart/End, SubagentStop, PostToolUse)
   -> POST /api/hooks/*   |   ActivityLogger middleware auto-logs mutations
   Vite polls /api/status (adaptive 2s/10s)   |   Docker Compose runs DB + PMA
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

The frontend polls with adaptive intervals (2s active, 10s idle). The backend follows a router -> service -> model pattern; an activity-logger middleware auto-records all POST/PATCH/DELETE operations.

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
+-- AgentMemory (human_memory mode, DWB-584)
+-- JournalEntry (human_memory mode, DWB-584)
```

### human_memory Mode (beta, DWB-584)

A per-project memory model that replaces the flat `memory.md` blob with rows. Off by default and gated behind `projects.memory_mode`, so a project that never enables it is unaffected. Spec: `docs/human_memory_spec.md`.

- `agent_memories` holds the RULE. Tiers are `raw` (written untiered during a session), `core`, `scar`, `scar_context_bound` and `working`. Carries `cost`, `caught_by` and `surprised`, which are read against memories rather than against episodes: the context scan gates on `cost`, and `caught_by` aggregated across agents is the map of where a team's own checks do not look.
- `journal_entries` holds the STORY. Never auto-loaded, queried by tag and date rather than read whole, and carries a permanent `retrieval_count` that never decays. Three retrievals promote an entry into memory.
- **There is no `score` column and there must never be one.** Score is a pure function of tier and sessions since the entry last fired, derived at read time. A stored score is a second authoritative copy of a derived fact and drifts out of sync with the rule that produces it. The same reasoning excludes a stored band and a stored session count.
- **The clock is sessions, not calendar days**, which is why reinforcement is `last_reinforced_session_id` rather than a timestamp. An agent idle for three weeks has forgotten nothing.
- `tier` is NOT NULL with `raw` as a named value rather than a nullable column, so a scoring query has to name `raw` to exclude it; a nullable column would let a join drop untiered rows silently.

Project-level columns added alongside: `memory_mode`, `memory_schema_version`, and `topoff_enabled` / `topoff_interval`. The top-off columns are deliberately unrelated to the memory columns beside them and share a migration for delivery reasons only; top-off is independent of memory mode and works on a `stock` project. `hook_sessions.prompt_count` supports the top-off interval.

`ProjectRead` exposes `memory_mode` and `memory_schema_version`; `memory_schema_version` is system-stamped and never accepted on update. Switching modes requires an explicit confirmation flag and returns a verbatim warning on the unconfirmed attempt, because switching rewrites every memory the project has.

### Tables

28 model files in `app/models/`. See individual model files for full column definitions.

| Table | Key Columns | Notes |
|-------|-------------|-------|
| **projects** | prefix, name, status, repo_path, jira_base_url, jira_project_key, tl/pm_overhead_tokens, tl/pm_overhead_time_seconds, force_headers, force_test_coverage, force_test_run, force_initial_md, force_architecture_md, force_handoff_md, force_consolidation, capture_agent_comms, playbooks_deployed_at | 7 sprint gate flags, all default OFF (opt-in). `capture_agent_comms` (default ON) gates inter-agent message capture. Status: active/paused/completed/archived |
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
| **score_event** | project_id, sprint_id, subject_agent_id, delta, source, trigger_type, actor_agent_id, actor_cost, reason, ref_type/ref_id, reverted_by, created_at | DWB-424 append-only scoring ledger (source of truth). source: auto/human/peer/**audit** (DWB-016; audit triggers `audit_grant`/`audit_demerit`, actor = The_Auditor, bypasses peer caps). Corrections append a reverting row; rows are never deleted |
| **standards_audit** | project_id, sprint_id, ticket_id, pr_ref, diff_range, verdict, violations, scorecard, summary (MEDIUMTEXT), run_at, triggered_by, created_at | DWB-014 fresh-auditor verdict store. verdict: pass/reject; `violations`/`scorecard` JSON. Recording raises an alert + feed entry; `apply-scorecard` is a separate, idempotent ledger write. Surfaced at `/projects/:id/audits` |
| **agent_score** | (agent_id, project_id) PK, reputation, influence, updated_at | DWB-424 derived cache, rebuildable from score_event. `reputation` = all-time rank; `influence` = per-sprint peer budget (ledger-derived, auto-resets) |
| **tl_messages** | from_agent_id, to_agent_id (NULL=broadcast), from_project_id, body, created_at | DWB-436 cross-project team-lead channel. NOT project-scoped; from_project_id only records the sender's home project |
| **tl_message_reads** | (message_id, agent_id) PK, read_at | DWB-436 per-(message, agent) read receipt; message_id FK ON DELETE CASCADE |
| **inter_agent_messages** | project_id, dwb_session_id, from/to_agent_id, from/to_agent_name, body, summary, created_at | DWB-446 captured SendMessage log. `*_name` always stored; FK ids nullable. `dwb_session_id` display-only (never purged on). Age-purged > 4 days |
| **instructions** | scope, project_id, agent_id, title, body | Scope: global/project/agent |
| **activity_log** | project_id, agent_id, entity_type, entity_id, action, details, created_at | Auto-populated by middleware |
| **test_results** | project_id, sprint_id, ticket_id, run_at, suite, total_tests, passed, failed, skipped, duration_seconds, status, details, triggered_by, triggered_context | Failed results auto-create failure_records |
| **hook_sessions** | session_id, transcript_path, agent_id, project_id, ticket_id, sprint_id, start_time, end_time, total_tokens, token_breakdown, status, session_type, agent_name, hook_event, created_at | Status: active/completed/error. Type: main/teammate/subagent |
| **error_logs** | project_id, agent_id, source, endpoint, error_type, message, stack_trace, file_path, function_name, line_number, status_code, created_at | Source: backend/frontend/hook |
| **failed_hooks** | session_id, hook_event, reason, cwd, agent_type, agent_name, agent_id_from_marker, project_id, hook_data, created_at | DWB-288 audit table for marker-resolution failures. Every `resolve_agent_from_marker` miss writes a row with the failure reason (`marker_missing`, `marker_unparseable`, `marker_agent_unknown`, etc.) and the raw hook payload, so the diagnostic isn't silent. |

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

- **Routers** (`app/routers/`): Define endpoints, validate input via Pydantic, inject DB session via `Depends(get_db)`. 25 router files.
- **Services** (`app/services/`): Business logic, cross-entity operations, auto-triggers (status history, rework detection, time computation, failure records, token attribution, tracking events, action capture, scoring, standards audits, demo seeding). 39 service files.
- **Models** (`app/models/`): SQLAlchemy 2.0 ORM classes with Mapped types and relationships. 28 model files.
- **Schemas** (`app/schemas/`): Pydantic v2 models with ConfigDict(from_attributes=True) for Create, Update, Read per entity. List endpoints use slim schemas that strip heavy fields (e.g., `TestResultListRead` omits `details`, `AgentListRead` omits `api_key`). Tickets, alerts, and sprints support `?fields=slim` for minimal payloads.
- **Middleware** (`app/middleware/`): ActivityLoggerMiddleware auto-logs all mutations.

### ActivityLoggerMiddleware

Intercepts all POST/PATCH/PUT/DELETE requests with 2xx responses and inserts an `activity_log` row.

Agent ID resolution priority: (1) `X-Agent-ID` header, (2) entity fields (`raised_by_agent_id`, `assigned_agent_id`), (3) generic body (`agent_id`, `author_agent_id`), (4) project PM/TL fallback for sprint/epic creation, (5) null (shows as "system").

Disabled during testing (`TESTING=1` env var).

### Endpoint Reference

Full OpenAPI reference at http://localhost:8000/docs (149 endpoints, 25 routers). The non-obvious / automation endpoints are catalogued in `README.md`. Notes that matter for the data model:

- `GET /api/projects/{id}/team` (single-roundtrip roster) returns `{project_id, project_prefix, agents: [{agent_id, name, role, is_active, assigned_at, last_seen, presumed_live}]}`, active-only unless `?include_inactive=true`.
- `GET /api/tracking/summary` `per_agent` rows aggregate `token_report` + `overhead_token_report` (a `tokens` total plus a separate `overhead_tokens`); `project_total.overhead_tokens` is the project-wide overhead figure.
- `POST /api/agents/identify` + `/spawn-prepare` resolve `(role, name, project_prefix)`, accepting the short name or `<name>_<PREFIX>` form.
- Agent memory (DWB-401) lives at `<repo>/.dwb/memory/<prefix>/<name>/` (outside `.claude/`, so subagents write it directly): `identity.md` (system-generated) + free-form `memory.md` (agent-written; merges old scratchpad + lessons, DB is the session index). Writes via `memory/append` + `session-complete`; `memory.md` has a 12000-token HARD write-ceiling (DWB-518): an over-ceiling write is refused with HTTP 400 and drops nothing, condense then retry. No passive drop-oldest trim exists any more. It is also not exempt from close: DWB-519 makes a memory write mandatory at least once per sprint for every active participant, and sprint close is refused, naming the non-writer, if one is missing.
- `GET /api/hooks/sessions?status=orphan&cutoff_minutes=60` returns stale active sessions for cleanup.
- DWB session lifecycle: `POST /api/sessions/open` (omit `opened_at`), `.../close` (headline required on ai_confident/ai_asked; consolidation gate opt-in via `force_consolidation`, default OFF, TL-owned docs only), `.../reopen` (undoes a false close; 409 if another is open).
- DWB session detection (DWB-402, Layer-2 Haiku retired): Layer-1 regex on open/close phrases, a SessionEnd transcript scan, slash commands (`/dwb-open`, `/dwb-close`), a 60-min idle sweeper. `ai_classifier` enum kept as a tombstone. Full reference: `docs/session_lifecycle.md`.
- Action capture (DWB-417/421): `POST /api/hooks/tool-use` (matcher-scoped PostToolUse) and `POST /api/hooks/lifecycle-event` (Notification / PreCompact) are fire-and-forget, always return 200, and write `tool_actions` rows.
- Scoring (epic 28): `GET .../scores` (leaderboard), `GET /api/agents/{id}/score` + `.../scores/agent?agent=NAME` (ledger), `POST .../scores/award` (human), `.../scores/peer` (peer, `X-Agent-ID`), `.../scores/rebuild`. See § 8.
- Standards audits (epic 10): `GET`/`POST /api/standards-audits` (list / record verdict + scorecard), `POST /api/standards-audits/{id}/apply-scorecard` (idempotent ledger write). See § 8.
- Team-lead channel (DWB-436/437): `GET /api/tl-channel` (cross-project, with `read_by` roster), `.../unread?agent_id=`, `POST /api/tl-channel` (role-guarded send), `.../mark-read`. See § 8.
- Inter-agent comms (DWB-446..449): `POST /api/hooks/agent-message` (capture), `GET`/`DELETE /api/projects/{id}/agent-messages` (log/clear). See § 8.

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
/projects/:id/comms                  -> InterAgentCommsPage
/projects/:id/sessions               -> SessionsPage
/projects/:id/sessions/current       -> SessionCurrentPage
/projects/:id/sessions/:sid          -> SessionDetailPage
/projects/:id/docs                   -> DocsPage
/projects/:id/audits                 -> AuditsPage
/docs                                -> SystemDocsPage
/instructions                        -> InstructionsPage
/tests                               -> TestResultsPage
/tests/:runId                        -> TestResultsPage (detail mode)
/errors                              -> ErrorLogPage
/archie-channel                      -> ArchieChannelPage
/help                                -> HelpPage
```

### Key UI Features

- **Status history timeline** on ticket detail pages
- **Failure record review form** with type, notes, root_cause, resolution
- **Test performance tab** with duration charts and sparklines
- **Tracking summary** with time/token rollups from hooks
- **Adaptive polling** 2s active, 10s idle
- **Help Center** (`/help`): in-app onboarding, quick-start flow + per-view help with live fuzzy search

### API Client Layer

`src/api/` wraps `client.js` (fetch + ApiError) with one module per resource (projects, sprints, epics, agents, tickets, comments, alerts, instructions, activityLogs, projectAgents, testResults, failureRecords, tokens, tracking, status, system, docs, agentMessages). Most are CRUD; richer ones add helpers (deployPlaybooks, alerts.dismissAll/requestTestRun/sendToTeam, instructions.sync, agentMessages get/clear).

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
| help.css      | Help Center page, fuzzy search, collapsible sections  |
| audits.css    | Standards Audits page, verdict badges, scorecard rows  |

Font: JetBrains Mono / Fira Code (monospace). BEM-inspired naming (`component__element`, `component--variant`).

### Help Center

`/help` (`pages/HelpPage.jsx`) is in-app onboarding. Top is a quick-start: a linear startup flow plus standalone shortcut callouts (rendered as separate regions, not chained). Below, domain sections mirror the sidebar nav, each a Why/How/Where summary + bullets. Content lives in `src/helpContent/`: `index.js` auto-discovers `sections/*.js` via `import.meta.glob` (drop a file, it renders, no wiring), `quickStart.js` holds the flow/callouts, `CONTRACT.md` defines the section shape. Three reusable presentational components in `components/help/`: `FuzzySearch` (+ `hooks/useFuzzyFilter`, dependency-free substring/subsequence matcher), `CollapsibleSection` (controlled open so search force-opens matches), `SummaryHeader`.

---

## 5. Scripts and Hooks

Backend CLI scripts in `backend/scripts/`: `migrate.sh`, `run_tests.sh`, `sync_instructions.py`. Repo-root `scripts/` holds the standards-audit runner (`run_standards_audit.sh` → `standards_audit.py`, § 8) and the git-hook installer.

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

**SubagentStop transcript fallback (DWB-311).** CC's synthetic `agent_transcript_path` often doesn't exist; the real transcript is interleaved in the parent's `.jsonl`, each line tagged `agentName`. When `parse_transcript()` returns 0, `_handle_subagent_stop()` falls back to `_parse_subagent_from_projects_dir` (sum usage where `agentName == agent.name`). Runs only when the primary parse misses and the marker named an agent; returns zero on failure, never worsening attribution.

**Marker-based attribution (DWB-294, 304).** SubagentStop session_ids are CC-internal, so the TL writes a **pending marker** at spawn: `.claude/agents/active/pending-<agent_id>-<unix_ms>-<rand4hex>` (JSON dict). `resolve_agent_from_marker` tries a literal `<session_id>` lookup, else **atomically renames** the oldest unconsumed `pending-*` marker for the project to `<session_id>` (consumed once). Failures write a `failed_hooks` row with a specific `reason`.

**Marker file format** (all marker files, both literal and pending, are JSON dicts):

```json
{"agent_id": 21, "agent_name": "Barry_DWB", "role": "backend-worker", "project_prefix": "DWB"}
```

`agent_id` is the only authoritative field for attribution; the others are convenience/diagnostic.

Workers get tokens on their active ticket (in_progress/in_review/recently-done ~5min); TL/PM get project overhead (`tl_overhead_tokens`/`pm_overhead_tokens`, DWB-305). Key files: `hook_tracking.py`, `routers/hooks.py` (endpoints never 5xx; failures -> `failed_hooks` + `error_logs`), `models/hook_session.py`, `models/failed_hook.py`.

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
- **Primary (passive):** lifecycle hooks capture tokens/time (§5); they increment `ticket.tokens_used` and project overhead fields directly. Worker priority: `in_progress` > `todo` > `in_review` > recently `done` (5 min).
- **Per-ticket:** `POST /api/tracking/tokens` (or legacy `POST /api/tickets/{id}/tokens`) inserts event + increments ticket **atomically** (ledger event + cache in one commit — DWB-022 fixed the old path that bumped `tokens_used` with no `tracking_log` row and left `token_source='unknown'`). Attributed to `X-Agent-ID` else the ticket assignee (400 if neither); `token_source` reflects the real path. Migration dwb022 reconciled 10 orphan tickets (~550k phantom tokens → `source='reconciled'`), so rollups are trustworthy going forward.
- **Per-project overhead:** `POST /api/projects/{id}/overhead` increments `tl_`/`pm_overhead_tokens`.
- **Audit/detail:** `GET /api/tokens/audit` (flags discrepancies), `GET /api/tickets/{id}/token-attribution`, `GET /api/tracking/summary` (per-ticket/agent/sprint rollups).

### Deterministic Action Capture
CC hooks capture actions passively (DWB-417..421): `PostToolUse` -> `/api/hooks/tool-use`, `Notification`/`PreCompact` -> `/api/hooks/lifecycle-event`. Each `tool_actions` row classifies an `event_type` and emits a feed verb; `message_sent` records the recipient only, never the body. Context resolves from `session_id` like session-end; all FKs nullable so a delivery gap never drops the row.

### Agent Scoring
Per-agent-per-project scoring (epic 28, DWB-424..428). Append-only `score_event` ledger = source of truth; `agent_score` = rebuildable cache. Two currencies: **reputation** (all-time rank) and **influence** (per-sprint peer budget, default 20, auto-resets). Values + caps in `app/config/scoring.py`.
- **Auto-triggers** (no agent action): ticket_closed (+ no-rework bonus), rework, test_failure, stale, zero_token_close, gate_miss, forgot. Attributed via `ticket.assigned_agent_id` / `failure_record.logged_by`, so the right worker is credited.
- **Human tools** (free): `/carrot` `/stick` `/score` `/leaderboard` -> `POST .../scores/award`.
- **Peer economy:** `POST .../scores/peer` (`X-Agent-ID`). Flat - any agent may carrot/stick any other; only self-scoring is barred.
- **Broadcast:** human + peer carrot/sticks notify all project agents via per-agent alerts (`alert.recipient_agent_id`); human critical, peer info. Auto-triggers do not broadcast.

### Standards Audit
Epic 10 (DWB-014..031). A diff is judged against the global standards sheet (`docs/rules/global/coding-standards.md`) plus the repo's `## Project Extensions` by a **fresh, context-starved auditor** — `scripts/run_standards_audit.sh` → `standards_audit.py` spawns a headless `claude -p` from a tempdir with ONLY the law + a facts-only attribution block + diff + a strict-JSON contract, so it can't rubber-stamp. Malformed output is never posted. `POST /api/standards-audits` records the verdict/violations/scorecard and raises an alert (info=pass, warning=reject) + a feed entry; `POST /{id}/apply-scorecard` is the separate idempotent step that writes deltas to `score_event` (`source=audit`). **The_Auditor** is a seeded system agent (id 51, role `auditor`, `project_id` NULL — migration dwb028) that owns those ledger rows and the feed attribution; `STANDARDS_AUDIT_AGENT_ID` in `.env` points at it, else the service resolves it by name. `force_standards_audit` (dwb017) gates sprint close on a passing audit in-window. UI: `/projects/:id/audits` (`AuditsPage`). How-to: README § Standards Audit.

### Archie Channel (Cross-Project TL Messaging)
`tl_messages` (DWB-436/437) is a cross-project team-lead channel: a message is direct (`to_agent_id` set) or broadcast (NULL = all other TLs); `tl_message_reads` tracks per-(message, agent) read state. Sender and any named recipient must be `role=team-lead` (else 400). A send pings the target or every other active TL via `alert.recipient_agent_id`. On spawn, unread renders atop `identity.md` and is marked read once shown; `/tl` replies. NOT project-scoped; `delete_project` clears messages sent from it.

### Inter-Agent Comms Capture
`inter_agent_messages` (DWB-446..449) logs native SendMessage traffic per project. The `PostToolUse` SendMessage hook -> `POST /api/hooks/agent-message` resolves the sender from `session_id` (same resolver as token attribution) and the recipient best-effort by name; `to_agent_name` is always stored even when the FK misses, and bodies ARE stored. Per-project `capture_agent_comms` (default ON) gates it (off = 200, stores nothing). `purge_old_agent_messages` drops rows older than 4 days on the idle sweeper, keying off `created_at` alone. List/clear: `GET`/`DELETE /api/projects/{id}/agent-messages`; UI at `/projects/:id/comms`.

### Session Write-up Synthesis
On every DWB session close (all paths + the idle sweeper, via `_apply_synthesis` in `close_session`) a deterministic synthesizer (`session_synthesizer.py`, NO LLM) builds from the session rollup: a headline (kept if the closer supplied one, else synthesized ~5-10 words - fixes null headlines on idle/regex closes), a structured `summary` JSON `{lead, sections:[{title,bullets}]}` on `dwb_sessions.summary`, and weighted keywords. Keywords come from `keyword_extraction.py` (pure: frequency rank + stopword drop, ticket keys verbatim, kebab-case) over an agent-text-only corpus (`_gather_corpus`, no user prompts - DWB-351), stored in the generic `entity_keywords` table (entity_type/entity_id/keyword/weight, both indexed) - substrate for future cross-entity linked relations. List + detail endpoints expose both (one batched keyword query). Synthesis is guarded (a failure never blocks a close) and idempotent on reopen. A one-shot backfill re-synthesizes legacy null-headline sessions via the same path.

### Alert Auto-Creation
- No alert on a 0-token close: closing a ticket with zero attributed tokens applies a `zero_token_close` score penalty (`scoring_triggers.py`), it has never raised an Alert row
- Sprint completed -> mints a test ticket onto the closing sprint as backlog, unassigned (DWB-566). No alert rows: the per-role tests-needed alerts were removed in DWB-463
- Doc gate failing -> critical alert for TL
- Rework detected -> info alert for PM
- Unattributed hook session -> warning alert

### Stale Ticket Detection
`POST /api/tickets/stale-check` — PM polls for tickets stuck in_progress beyond a threshold. Creates a deduped warning alert (matches on ticket_key + minutes in title, only checks open/acknowledged). Resolves PM as alert raiser, falls back to assigned agent, then any project agent.

### ALERTS_PENDING.md Lifecycle
`POST /api/alerts/send-to-team?project_id=X` writes open alerts to `.claude/ALERTS_PENDING.md` and tags each with `user_sent_at`. When all of a project's alerts are resolved/dismissed, `_auto_unlink_alerts_file()` deletes the file (after `dismiss_all()` / `update_alert()` changes).

### Failure Analysis
- Manual records: A-G taxonomy (context_degradation, spec_drift, sycophantic_confirmation, tool_selection_error, cascading_failure, silent_failure, integration_failure)
- Auto-detected: rework (from status_history), test_failure (from test results)
- Sprint gate: unreviewed stubs block close
- Summary endpoint: aggregated by type, agent, sprint, trend

### Ticket Deletion Cascade
Deleting a ticket cascades through: comments, status_history, alerts, test_results, failure_records, tracking_log, hook_sessions — all via `ondelete=CASCADE` on FKs and `cascade="all, delete-orphan"` / `cascade="all, delete"` on relationships.

### Project Deletion Cascade
Deleting a project cascades through: alerts, test_results, activity_logs, instructions, inter_agent_messages, tl_messages (sent-from), tickets (and their children per above), failure_records, project_agents, sprints, epics.

### Jira Integration
Projects optionally link to a Jira project via `jira_project_key`. DWB tickets map 1:1 to Jira issues via `jira_issue_key` (unique constraint); a duplicate key returns a clean 409 on both create and update/PATCH (DWB-465/476), never a raw 500. `POST /api/projects/{id}/disable-jira` clears all Jira links from the project and its tickets. Jira data is never modified.

---

## 9. Operational Gotchas and Traps

Hard-won properties of this environment. None of these are bugs anyone introduced; they are how the dev loop behaves, and each has cost a real outage.

### Saving an ORM model is a schema change to the shared database

`app/main.py` calls `Base.metadata.create_all(bind=engine)` in the FastAPI lifespan. Uvicorn runs with `--reload`. So the moment a model file is saved, the server restarts and creates any new tables in whatever database it is pointed at, which in development is the live one.

The dangerous half is what it does NOT do: `create_all` creates missing tables, and never adds columns to tables that already exist. Adding a column to an existing model therefore produces the worst combination. The ORM begins selecting a column the schema does not have, and every read of that table returns 500 until the migration lands.

Two consequences worth planning around:

- **The outage window is avoidable for a purely additive migration, and only forced when the model and the schema changes depend on each other.** This paragraph previously said the window was unavoidable, full stop, and that is wrong. It was written from the column-added-to-an-existing-table case, where `create_all` cannot help you and the ORM starts selecting what the schema lacks the moment you save.

  **If the migration only ADDS tables or widens an enum, apply the migration FIRST and save the models AFTER.** `create_all` then finds the table already present and does nothing, and there is no window at all. Proven on DWB-593: `/api/projects` returned 200 before, during and after.

  **Save-then-apply is only necessary when the two changes are mutually dependent.** There you still keep the window to seconds: edit the migration first, prove it on a scratch database, and only then save the models and apply the DDL back to back.

  **A MIXED migration, one that both adds a table and removes a column, has no safe order and you must plan for the race.** Save first and `create_all` builds the new table from the model before alembic reaches it, so the migration aborts partway with the version unmoved. Apply first and the old model selects a column the schema no longer has until you save. Proven on DWB-593, which hit the first of those. The mitigation when it happens is to drop what `create_all` made and re-run; the better move is to split the migration so the additive half can go first.

- **A new table with a foreign key to `projects` must be added to the project delete cascade.** Every FK to `projects` here is NO ACTION, so a table missing from the cascade does not fail at the model layer, it 500s the delete endpoint. Found on DWB-593 by deleting a throwaway project and getting a 500 instead of a 204. The same applies to the ticket cascade for anything keyed on a ticket.
- **A later `alembic upgrade head` can fail with "table already exists"**, because `create_all` got there first. That failure is not evidence the migration is wrong. Check whether the tables are empty and were created by startup before concluding anything about the migration file.

Tell anyone working in the same tree before opening that window. A few seconds of missing-column errors looks exactly like their own bug.

### A create_all schema and a migration schema are not the same schema

They disagree about server defaults. Several `projects.force_*` columns are NOT NULL with no default on a migration-built database and NOT NULL with a default on a `create_all`-built one. There will be other cases; these are the ones found so far.

This matters more than it sounds, because `lat_test` is built by `create_all` from the models while live is built by migrations. So a green test suite proves the code matches the MODELS. It does not prove the code matches PRODUCTION, and those are different claims. State which one you are making.

Practical consequence: any test doing a raw INSERT is correct against one target and wrong against the other. Discover required columns from `information_schema` rather than hardcoding a list, because a hardcoded list is correct against exactly one of the two and the gap between them is what the test exists to span.

### Alembic never calls create_all

`alembic/env.py` contains no `create_all`. The only one in the backend is the startup call above. These are separate mechanisms with separate blast radii and conflating them produces wrong diagnoses: a migration failing on "already exists" points at the running API, not at alembic.

`env.py` overwrites `sqlalchemy.url` from a module-level settings singleton, so setting it on a `Config` object in-process is silently ignored. The only override that survives is a subprocess with a different `MYSQL_DATABASE`, which has the side benefit of running the command a person would actually type.

### Testing a migration against an empty database proves less than it looks

Replaying from base into an empty database tests that a fresh clone gets the schema from migrations alone, which is a real requirement and worth keeping. It does not test the migration against a populated schema at the previous revision, which is the case that actually runs in anger.

Both are needed. A migration can pass the first and fail the second, and `alembic current` reporting a revision is not evidence that any table was created. Introspect for the tables and columns, not the version number.

### MySQL DDL is not transactional

A migration that fails partway leaves the schema changed and `alembic_version` unmoved. The re-run then behaves as a silent no-op or fails on objects that already exist. Round-trip every migration down and up before landing it; a downgrade that merely exists has not been tested.

Specifically: MySQL refuses to drop an index a foreign key still needs (errno 1553), so explicit `drop_index` calls before `drop_table` will fail. Dropping the table removes its indexes anyway.

### Subagents cannot write under `.claude/`

Permission dialogs for those paths kill a subagent in the ink renderer. The team lead runs with a human attached and is the only agent that can edit them. Agent memory lives in `.dwb/` for this reason and is written through the API, never by direct file edit.
