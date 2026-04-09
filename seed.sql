-- D'Waantu B'Guantu seed data
-- Run: docker exec -i lat_mysql mysql -h 127.0.0.1 -u lat_user -plat_dev_password local_agent_tracker < seed.sql

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE activity_log;
TRUNCATE TABLE comments;
TRUNCATE TABLE alerts;
TRUNCATE TABLE instructions;
TRUNCATE TABLE tickets;
TRUNCATE TABLE project_agents;
TRUNCATE TABLE sprints;
TRUNCATE TABLE epics;
TRUNCATE TABLE projects;
TRUNCATE TABLE agents;
TRUNCATE TABLE test_results;
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- AGENTS (unique per project — no shared agents)
-- ============================================================
INSERT INTO agents (id, name, description, role, api_key, is_active) VALUES
-- DWB agents
(1,  'Archie', 'Lead architect — plans sprints, delegates work, reviews PRs. Claude role: team-lead',              'team-lead',        'key-archie-001',   1),
(2,  'Mona',   'Project manager — tracks progress, updates tickets, flags blockers. Claude role: pm',              'pm',               'key-mona-002',     1),
(3,  'Pixel',  'Frontend developer — React, CSS, component architecture. Claude role: frontend-worker',            'frontend-worker',  'key-pixel-003',    1),
(4,  'Devin',  'Backend developer — FastAPI, SQLAlchemy, database migrations. Claude role: backend-worker',        'backend-worker',   'key-devin-004',    1),
(5,  'Bolt',   'Infrastructure and DevOps — Docker, CI/CD, deployment. Claude role: system-ops',                   'system-ops',       'key-bolt-005',     1),
(6,  'Sage',   'QA specialist — writes tests, runs E2E suites, files bugs. Claude role: tester',                   'tester',           'key-sage-006',     1),
-- INGEST agents
(7,  'Conduit',  'Lead — designs pipeline architecture, manages data flow strategy',         'team-lead',   'key-conduit-007',  1),
(8,  'Parser',   'Developer — builds source connectors, handles format detection',           'developer',   'key-parser-008',   1),
(9,  'Valve',    'Developer — transform rules, validation, schema enforcement',              'developer',   'key-valve-009',    1),
-- RECON agents
(10, 'Ledger',   'Lead — reconciliation strategy, matching algorithm design',                'team-lead',   'key-ledger-010',   1),
(11, 'Tally',    'Developer — transaction comparison engine, fuzzy matching',                'developer',   'key-tally-011',    1),
-- DOCS agents
(12, 'Scribe',   'Lead — content organization, information architecture',                    'team-lead',   'key-scribe-012',   0),
(13, 'Index',    'Developer — search implementation, Astro components',                      'developer',   'key-index-013',    0);

-- ============================================================
-- PROJECTS
-- ============================================================
INSERT INTO projects (id, prefix, name, description, status, tl_overhead_tokens, pm_overhead_tokens, repo_path) VALUES
(1, 'DWB',    'D''Waantu B''Guantu Portal',   'Multi-agent workflow dashboard — monitor progress, manage team instructions, track token spend',  'active',    48200,  31500, '/Users/mchick/Dev/d-waantu_b-guantu'),
(2, 'INGEST', 'Pipeline Ingestion Engine',     'ETL pipeline for normalizing vendor data feeds into a unified schema',                           'active',    12400,   8700,  NULL),
(3, 'RECON',  'Reconciliation Service',        'Nightly job that cross-references transactions between internal ledger and upstream providers',  'paused',     5100,   3200,  NULL),
(4, 'DOCS',   'Internal Knowledge Base',       'Searchable docs site built with Astro — runbooks, onboarding guides, architecture decisions',   'completed',  2800,   1900,  NULL);

-- ============================================================
-- PROJECT-AGENT ASSIGNMENTS
-- ============================================================
INSERT INTO project_agents (project_id, agent_id) VALUES
(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
(2, 7), (2, 8), (2, 9),
(3, 10), (3, 11),
(4, 12), (4, 13);

-- ============================================================
-- EPICS
-- ============================================================
INSERT INTO epics (id, project_id, name, description, status) VALUES
(1, 1, 'Core Dashboard',          'Main dashboard layout, project cards, agent status, activity feed',              'completed'),
(2, 1, 'API Layer',               'FastAPI routers, schemas, services for all entities',                            'completed'),
(3, 1, 'Live Data Wiring',        'Replace placeholder data with real API calls, adaptive polling, Zustand hooks',  'in_progress'),
(4, 1, 'Instruction Management',  'CRUD UI for global/project/agent-scoped instructions',                          'open'),
(5, 2, 'Source Connectors',       'Adapters for each vendor feed format (CSV, XML, JSON)',                          'in_progress'),
(6, 2, 'Transform Pipeline',      'Normalization rules, field mapping, validation',                                 'open'),
(7, 3, 'Ledger Comparison',       'Diff engine for matching internal vs upstream transactions',                     'in_progress');

-- ============================================================
-- SPRINTS
-- ============================================================
INSERT INTO sprints (id, project_id, name, goal, sprint_number, status, start_date, end_date) VALUES
(1, 1, 'Project Tests + Archive/Delete',                        'Scaffold frontend + DB models',       1, 'completed', '2026-03-20', '2026-03-23'),
(2, 1, 'Token Tracking Hooks',                                 'API layer + live data wiring',        2, 'active',    '2026-03-24', '2026-03-27'),
(3, 1, 'Overhead Tracking + Agent Naming + Test Cadence',      'Instruction management + polish',     3, 'planned',   '2026-03-28', '2026-03-31'),
(4, 2, 'INGEST Sprint 1', 'CSV and XML connectors',              1, 'active',    '2026-03-22', '2026-03-28'),
(5, 3, 'RECON Sprint 1',  'Ledger diff prototype',               1, 'active',    '2026-03-18', '2026-03-25');

-- ============================================================
-- TICKETS
-- ============================================================

-- DWB Sprint 1 (completed)
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds, completed_at) VALUES
(1,  1, 1, 1, 3, 1, 'DWB-001', 'Set up Docker + MySQL + Alembic',                'docker-compose, .env, initial migration with all 10 models',           'task',  'done',  18400, 1200, '2026-03-21 14:30:00'),
(2,  1, 1, 1, 4, 2, 'DWB-002', 'Scaffold Vite + React + Zustand',                'Project scaffold, routing, Zustand store, placeholder data',           'task',  'done',  24600, 1800, '2026-03-21 16:45:00'),
(3,  1, 1, 1, 4, 3, 'DWB-003', 'Build dashboard layout and components',          'AppShell, Sidebar, Header, Footer, DashboardPage with project cards',  'story', 'done',  31200, 2400, '2026-03-22 11:20:00'),
(4,  1, 1, 1, 4, 4, 'DWB-004', 'Terminal-aesthetic CSS theme',                    'CSS custom properties, JetBrains Mono, dark bg, green/orange palette', 'task',  'done',  12800,  900, '2026-03-22 13:00:00');

-- DWB Sprint 2 (active)
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds, completed_at) VALUES
(5,  1, 2, 2, 3,    5,  'DWB-005', 'Build FastAPI routers and schemas',           'Pydantic schemas, CRUD services, RESTful endpoints for all 10 models', 'story', 'done',  42100, 2700, '2026-03-25 10:15:00'),
(6,  1, 2, 2, 3,    6,  'DWB-006', 'Status endpoint for adaptive polling',        'GET /api/status — active agents, open alerts, in-progress tickets',    'task',  'done',   8900,  600, '2026-03-25 11:00:00'),
(7,  1, 3, 2, 4,    7,  'DWB-007', 'Frontend API client and polling hooks',       'Fetch wrapper, per-resource hooks, adaptive polling (2s/10s)',         'story', 'done',  35800, 2100, '2026-03-26 09:30:00'),
(8,  1, 3, 2, 4,    8,  'DWB-008', 'Wire Zustand store to live API data',         'Remove placeholder imports, computed dashboard, real mutations',        'task',  'in_progress', 14200, 900, NULL),
(9,  1, 4, 2, NULL,  9,  'DWB-009', 'Instruction list page with scope filters',   'Filter by global/project/agent, display instruction cards',            'story', 'todo',  0, 0, NULL),
(10, 1, 4, 2, NULL, 10, 'DWB-010', 'Instruction create/edit modal',               'Form for creating and editing instructions with scope selection',      'story', 'backlog', 0, 0, NULL);

-- DWB Sprint 3 (planned)
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds) VALUES
(11, 1, 3, 3, NULL, 11, 'DWB-011', 'Agent detail page with token history',        'Per-agent view showing assigned tickets, token usage over time',        'story', 'backlog', 0, 0),
(12, 1, 4, 3, NULL, 12, 'DWB-012', 'Sidebar nav restructure',                     'Nest agents and tickets under projects in the sidebar',                'task',  'backlog', 0, 0);

-- INGEST Sprint 1
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds) VALUES
(13, 2, 5, 4, 8,    1, 'INGEST-001', 'CSV connector with header detection',       'Auto-detect delimiters, handle quoted fields, map to unified schema',   'story', 'in_progress', 22300, 1500),
(14, 2, 5, 4, 9,    2, 'INGEST-002', 'XML connector with XPath mapping',          'Parse nested XML feeds, configurable XPath for field extraction',       'story', 'todo',  0, 0),
(15, 2, 6, 4, NULL,  3, 'INGEST-003', 'Validation rules engine',                  'Pluggable validators: required fields, type checks, range constraints', 'story', 'backlog', 0, 0),
(19, 2, 5, 4, NULL,  4, 'INGEST-004', 'CSV connector chokes on BOM-prefixed files','UTF-8 BOM bytes cause first header field to be misread',              'bug', 'todo', 0, 0);

-- RECON Sprint 1
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds) VALUES
(16, 3, 7, 5, 11,   1, 'RECON-001', 'Transaction matcher prototype',              'Fuzzy match on amount + date + reference, configurable tolerance',      'story', 'in_review', 28700, 2000),
(17, 3, 7, 5, NULL,  2, 'RECON-002', 'Unmatched transaction report',              'Generate CSV of unmatched items with suggested matches',                'task',  'todo',  0, 0);

-- DWB bug
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds) VALUES
(18, 1, 2, 2, 3, 13, 'DWB-013', 'PATCH /api/tickets returns 500 on empty body',  'Pydantic validation error when all fields are optional but body is {}', 'bug', 'in_progress', 3200, 180);

-- ============================================================
-- INSTRUCTIONS
-- ============================================================
INSERT INTO instructions (id, scope, project_id, agent_id, title, body) VALUES
(1, 'global',  NULL, NULL, 'Code style',              'Use consistent naming: snake_case for Python, camelCase for JS. No abbreviations in public APIs.'),
(2, 'global',  NULL, NULL, 'Commit messages',         'Imperative mood, max 72 chars first line. Body explains why, not what.'),
(3, 'project', 1,    NULL, 'CSS rules for DWB',       'Plain CSS with custom properties only. No Tailwind, no CSS-in-JS. Styles in dedicated .css files, never inline.'),
(4, 'project', 2,    NULL, 'INGEST error handling',   'All connectors must raise ConnectorError with source_file and line_number. Never silently drop records.'),
(5, 'agent',   NULL, 4,    'Devin backend standards', 'Always use SQLAlchemy 2.0 style (select() not query()). Type hints on all function signatures.'),
(6, 'agent',   NULL, 8,    'Parser conventions',       'All connectors must implement detect() and parse() methods. Return typed DataFrames, never raw dicts.');

-- ============================================================
-- COMMENTS
-- ============================================================
INSERT INTO comments (id, ticket_id, author_agent_id, body) VALUES
(1, 5,  1, 'Schemas look good. Make sure all list endpoints support filtering by parent ID.'),
(2, 5,  3, 'Done — added query params for project_id, sprint_id, etc. on all relevant routers.'),
(3, 7,  1, 'Use a single polling loop that fetches all resources in parallel, not one timer per resource.'),
(4, 7,  4, 'Implemented with Promise.all inside useAppData hook. Status endpoint drives the interval.'),
(5, 16, 10, 'Fuzzy matching looks solid. Add a confidence score to the output so we can threshold later.'),
(6, 18, 2,  'Flagging — this blocks the frontend from saving ticket edits. Marking as high priority.'),
(7, 13, 7,  'Make sure the header detector handles TSV as well as CSV. Some vendor feeds use tabs.'),
(8, 13, 8,  'Good call — added tab to the delimiter candidates list.');

-- ============================================================
-- ALERTS
-- ============================================================
INSERT INTO alerts (id, project_id, raised_by_agent_id, ticket_id, title, body, severity, status) VALUES
(1, 1, 2, 18, 'Ticket update endpoint broken',     'PATCH /api/tickets/{id} returns 500 when body has no fields. Blocks frontend save.', 'warning',  'open'),
(2, 2, 7, NULL, 'INGEST schema not finalized',      'Transform pipeline is blocked until we lock down the unified schema definition.',    'info',     'open'),
(3, 1, 2, NULL, 'Sprint 2 deadline approaching',    'Two tickets still in progress with 1 day remaining in the sprint.',                 'warning',  'acknowledged'),
(4, 3, 10, 16, 'RECON matcher needs review',        'Transaction matcher is in review — need sign-off before moving to done.',            'info',     'resolved');

-- ============================================================
-- ACTIVITY LOG
-- ============================================================
INSERT INTO activity_log (project_id, agent_id, entity_type, entity_id, action, details) VALUES
(1, 3,  'ticket',  1, 'completed',  '{"ticket_key":"DWB-001","title":"Set up Docker + MySQL + Alembic"}'),
(1, 4,  'ticket',  2, 'completed',  '{"ticket_key":"DWB-002","title":"Scaffold Vite + React + Zustand"}'),
(1, 4,  'ticket',  3, 'completed',  '{"ticket_key":"DWB-003","title":"Build dashboard layout and components"}'),
(1, 4,  'ticket',  4, 'completed',  '{"ticket_key":"DWB-004","title":"Terminal-aesthetic CSS theme"}'),
(1, 3,  'ticket',  5, 'completed',  '{"ticket_key":"DWB-005","title":"Build FastAPI routers and schemas"}'),
(1, 3,  'ticket',  6, 'completed',  '{"ticket_key":"DWB-006","title":"Status endpoint for adaptive polling"}'),
(1, 4,  'ticket',  7, 'completed',  '{"ticket_key":"DWB-007","title":"Frontend API client and polling hooks"}'),
(1, 4,  'ticket',  8, 'started',    '{"ticket_key":"DWB-008","title":"Wire Zustand store to live API data"}'),
(1, 3,  'ticket', 18, 'started',    '{"ticket_key":"DWB-013","title":"PATCH /api/tickets returns 500 on empty body"}'),
(2, 8,  'ticket', 13, 'started',    '{"ticket_key":"INGEST-001","title":"CSV connector with header detection"}'),
(3, 11, 'ticket', 16, 'review',     '{"ticket_key":"RECON-001","title":"Transaction matcher prototype"}'),
(1, 2,  'alert',   1, 'created',    '{"title":"Ticket update endpoint broken","severity":"warning"}'),
(2, 7,  'alert',   2, 'created',    '{"title":"INGEST schema not finalized","severity":"info"}'),
(1, 1,  'sprint',  2, 'started',    '{"name":"DWB Sprint 2","goal":"API layer + live data wiring"}');
