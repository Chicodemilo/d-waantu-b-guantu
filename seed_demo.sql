-- D'Waantu B'Guantu demo seed
-- Minimal "touring" dataset: 1 project, 3 agents, 1 epic, 1 sprint, 4 tickets.
-- Used by QUICKSTART so newcomers see a populated dashboard without inheriting
-- this repo's own internal project rows.
--
-- Run: mysql -h 127.0.0.1 -P 23847 -u lat_user -plat_dev_password local_agent_tracker < seed_demo.sql

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
-- AGENTS
-- ============================================================
INSERT INTO agents (id, name, description, role, api_key, is_active) VALUES
(1, 'Atlas', 'Team lead — orchestrates work, reviews PRs',         'team-lead', 'demo-atlas-001', 1),
(2, 'Pam',   'Project manager — tracks tickets, flags blockers',   'pm',        'demo-pam-002',   1),
(3, 'Spark', 'Developer — implements features end-to-end',          'developer', 'demo-spark-003', 1);

-- ============================================================
-- PROJECTS
-- ============================================================
INSERT INTO projects (id, prefix, name, description, status, tl_overhead_tokens, pm_overhead_tokens, repo_path) VALUES
(1, 'DEMO', 'Demo Project', 'Touring dataset — feel free to delete after exploring the dashboard', 'active', 8000, 5000, NULL);

-- ============================================================
-- PROJECT-AGENT ASSIGNMENTS
-- ============================================================
INSERT INTO project_agents (project_id, agent_id) VALUES
(1, 1), (1, 2), (1, 3);

-- ============================================================
-- EPICS
-- ============================================================
INSERT INTO epics (id, project_id, name, description, status) VALUES
(1, 1, 'Initial Build', 'Sample epic showing how dashboard structure renders', 'in_progress');

-- ============================================================
-- SPRINTS
-- ============================================================
INSERT INTO sprints (id, project_id, epic_id, name, goal, sprint_number, status, start_date, end_date) VALUES
(1, 1, 1, 'Demo Sprint 1', 'Walk through the dashboard end-to-end', 1, 'active', '2026-05-20', '2026-05-27');

-- ============================================================
-- TICKETS
-- ============================================================
INSERT INTO tickets (id, project_id, epic_id, sprint_id, assigned_agent_id, ticket_number, ticket_key, title, description, ticket_type, status, tokens_used, time_spent_seconds, completed_at) VALUES
(1, 1, 1, 1, 3,    1, 'DEMO-001', 'Set up the demo',           'Sample completed ticket — shows what a done card looks like',    'task',  'done',        12000, 900,  '2026-05-22 14:00:00'),
(2, 1, 1, 1, 3,    2, 'DEMO-002', 'Build the example feature', 'Sample in-progress ticket — shows active-work styling',          'story', 'in_progress',  4200, 300,  NULL),
(3, 1, 1, 1, NULL, 3, 'DEMO-003', 'Write tests for the demo',  'Sample todo ticket — unassigned, waiting for pickup',            'task',  'todo',            0,   0,  NULL),
(4, 1, 1, 1, NULL, 4, 'DEMO-004', 'Ship the demo to staging',  'Sample backlog item — illustrates the backlog state',            'task',  'backlog',         0,   0,  NULL);

-- ============================================================
-- INSTRUCTIONS
-- ============================================================
INSERT INTO instructions (id, scope, project_id, agent_id, title, body) VALUES
(1, 'global',  NULL, NULL, 'Code style',         'Imperative commits, consistent naming, type hints on public APIs.'),
(2, 'project', 1,    NULL, 'Demo project rule',  'This is a sample instruction so you can see how scoped instructions render.');

-- ============================================================
-- COMMENTS
-- ============================================================
INSERT INTO comments (id, ticket_id, author_agent_id, body) VALUES
(1, 2, 1, 'Architecture looks fine — proceed with implementation.'),
(2, 2, 2, 'Tracking — should land before sprint end.');

-- ============================================================
-- ALERTS
-- ============================================================
INSERT INTO alerts (id, project_id, raised_by_agent_id, ticket_id, title, body, severity, status) VALUES
(1, 1, 2, NULL, 'Sample alert', 'Demo alert so you can see how alerts render in the sidebar.', 'info', 'open');

-- ============================================================
-- ACTIVITY LOG
-- ============================================================
INSERT INTO activity_log (project_id, agent_id, entity_type, entity_id, action, details) VALUES
(1, 3, 'ticket', 1, 'completed', '{"ticket_key":"DEMO-001","title":"Set up the demo"}'),
(1, 3, 'ticket', 2, 'started',   '{"ticket_key":"DEMO-002","title":"Build the example feature"}'),
(1, 1, 'sprint', 1, 'started',   '{"name":"Demo Sprint 1","goal":"Walk through the dashboard end-to-end"}');
