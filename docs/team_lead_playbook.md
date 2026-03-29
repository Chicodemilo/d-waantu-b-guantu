# Team Lead Playbook

> How a Team Lead agent operates inside D'Waantu B'Guantu.
> Base URL: `http://localhost:8000`

---

## 1. Project Setup

Before anything moves, the project needs to exist.

### Quick start — from an existing repo

```
POST /api/projects/from-repo
{ "repo_path": "/path/to/repo" }
```

This scans the repo for `package.json`, `pyproject.toml`, `README.md`, and auto-populates prefix, name, and description. It also enables `force_initial_md` and `force_architecture_md` gates by default.

### Manual creation

```
POST /api/projects
{
  "prefix": "DWB",
  "name": "D'Waantu B'Guantu",
  "description": "Local agent tracker — sprint management for AI agents",
  "repo_path": "/Users/mchick/Dev/local_agent_tracker"
}
```

Fields that matter:
- `prefix` — short uppercase tag (max 6 chars), used to generate ticket keys (e.g. `DWB-001`)
- `repo_path` — optional filesystem path to the repo, useful for test runners and scripts
- `status` — one of `active`, `paused`, `completed`, `archived`. Default: `active`

Update with `PATCH /api/projects/{id}`. Track overhead tokens and time here — the TL is responsible for logging `tl_overhead_tokens` and `tl_overhead_time_seconds` periodically.

---

## 1b. First-Run Checklist (New Projects)

After creating a project, immediately:

### Check gate status
```
GET /api/projects/{id}/gate-status
```

This returns which documentation gates are passing or failing. If `force_initial_md` or `force_architecture_md` are enabled (they are by default for from-repo projects), the gate will fail until those files exist.

### Handle empty repos
If the repo is empty or has no meaningful structure:
1. Ask the user: *"What is this project? What's the goal? What are the constraints?"*
2. Update the project with their answers: `PATCH /api/projects/{id}` (description, name)
3. Write `INITIAL.md` at the repo root covering: why, requirements, phases, design decisions, constraints, success criteria
4. Write `ARCHITECTURE.md` once the system design is decided

### Create initial structure
1. Create the first epic: `POST /api/epics` — name it after the first major milestone
2. Create the first sprint: `POST /api/sprints` — set a goal, assign a start/end date
3. Assign agents to the project: `POST /api/project-agents` — at minimum, assign TL, PM, and one worker
4. Have the PM check gate status and raise alerts for anything missing

---

## 2. Sprints

Sprints give work a timebox and a goal.

```
POST /api/sprints
{
  "project_id": 1,
  "name": "Sprint 1 — Foundation",
  "goal": "Core models, API, basic frontend shell",
  "sprint_number": 1,
  "start_date": "2026-03-25",
  "end_date": "2026-04-01"
}
```

Sprint statuses: `planned` -> `active` -> `completed`

Move a sprint to `active` when work begins:
```
PATCH /api/sprints/{id}
{ "status": "active" }
```

Only one sprint should be `active` at a time. Close it when the timebox ends or when all tickets are `done`.

List sprints for a project: `GET /api/sprints?project_id=1`

---

## 3. Epics

Epics group related tickets under a theme.

```
POST /api/epics
{
  "project_id": 1,
  "name": "Backend API",
  "description": "All FastAPI models, routes, and services"
}
```

Epic statuses: `open` -> `closed`

Use epics to organize work by feature area. A ticket can optionally belong to one epic.

---

## 4. Managing Agents

Agents are the workers. Register them globally, then assign to projects.

Register an agent:
```
POST /api/agents
{
  "name": "backend-worker",
  "role": "developer",
  "description": "Handles FastAPI, SQLAlchemy, and Python work"
}
```

Roles: `team_lead`, `pm`, `developer`, `reviewer`, `specialist`

Assign to a project:
```
POST /api/project-agents
{
  "project_id": 1,
  "agent_id": 3
}
```

List agents on a project: `GET /api/project-agents?project_id=1`

---

## 5. Tickets — The Core Unit of Work

Every piece of work is a ticket. The TL creates, assigns, and tracks them.

```
POST /api/tickets
{
  "project_id": 1,
  "sprint_id": 1,
  "epic_id": 2,
  "assigned_agent_id": 3,
  "ticket_number": 1,
  "ticket_key": "DWB-001",
  "title": "Create test results DB schema and API endpoints",
  "description": "Model, schema, service, router for test_results table.",
  "ticket_type": "task",
  "status": "todo"
}
```

### Ticket types
- `task` — standard unit of work
- `bug` — something broken that needs fixing
- `story` — feature from a user perspective

### Ticket statuses (the flow)
```
backlog -> todo -> in_progress -> in_review -> done
```

The TL moves tickets through this pipeline:
- `backlog` — known work, not yet planned for a sprint
- `todo` — planned for current sprint, ready to pick up
- `in_progress` — agent is actively working on it
- `in_review` — work is done, TL is reviewing
- `done` — accepted and closed

### Assigning work
Set `assigned_agent_id` when creating or updating a ticket. An unassigned ticket has `null` for this field.

### Tracking effort
After an agent finishes, update the ticket with token/time usage:
```
PATCH /api/tickets/{id}
{
  "status": "done",
  "tokens_used": 45000,
  "time_spent_seconds": 120,
  "completed_at": "2026-03-27T15:20:00"
}
```

### Querying tickets
- By project: `GET /api/tickets?project_id=1`
- By sprint: `GET /api/tickets?sprint_id=1`
- By agent: `GET /api/tickets?assigned_agent_id=3`
- By status: `GET /api/tickets?status=in_progress`
- Combine filters: `GET /api/tickets?project_id=1&status=todo&sprint_id=1`

---

## 6. Instructions — Behavioral Rules

Instructions tell agents how to behave. Three scopes:

### Global (applies to all agents on all projects)
```
POST /api/instructions
{
  "scope": "global",
  "title": "Commit message style",
  "body": "Use conventional commits. No AI attribution."
}
```

### Project-scoped
```
POST /api/instructions
{
  "scope": "project",
  "project_id": 1,
  "title": "CSS rules",
  "body": "Plain CSS only. No Tailwind."
}
```

### Agent-scoped
```
POST /api/instructions
{
  "scope": "agent",
  "agent_id": 3,
  "title": "Backend standards",
  "body": "Follow existing patterns in app/models, app/routers, etc."
}
```

List and filter: `GET /api/instructions?scope=project&project_id=1`

### Sync with Claude memory
The system can compare instructions against Claude's memory files:
- `GET /api/instructions/sync-check` — see what's matched, memory-only, or db-only
- `POST /api/instructions/sync` — import unmatched memory entries as global instructions

---

## 7. Comments

Add context to tickets. Use for status updates, review notes, questions.

```
POST /api/comments
{
  "ticket_id": 5,
  "agent_id": 1,
  "body": "Schema created. Migration ran. All endpoints verified."
}
```

List comments on a ticket: `GET /api/comments?ticket_id=5`

---

## 8. Alerts — Escalation Path

When something needs human attention or is blocking work, raise an alert.

```
POST /api/alerts
{
  "project_id": 1,
  "raised_by_agent_id": 1,
  "ticket_id": 5,
  "title": "Migration failed on MySQL 8.0",
  "body": "Alembic autogenerate produced empty migration. Table already existed via create_all.",
  "severity": "warning"
}
```

Severities: `info`, `warning`, `critical`

Alert statuses: `open` -> `acknowledged` -> `resolved`

### When to raise alerts
- **info** — FYI, no action needed. ("Sprint goal achieved ahead of schedule.")
- **warning** — needs attention soon. ("Agent blocked on unclear requirements.")
- **critical** — needs immediate human attention. ("Database connection failing.", "Agent stuck in loop.")

Acknowledge and resolve:
```
PATCH /api/alerts/{id}
{ "status": "acknowledged" }

PATCH /api/alerts/{id}
{ "status": "resolved", "resolved_at": "2026-03-27T16:00:00" }
```

---

## 9. Activity Log

Log significant events for audit trail.

```
POST /api/activity-logs
{
  "project_id": 1,
  "agent_id": 1,
  "entity_type": "ticket",
  "entity_id": 5,
  "action": "status_change",
  "details": "Moved DWB-005 from todo to in_progress"
}
```

Query: `GET /api/activity-logs?project_id=1&entity_type=ticket&limit=20`

---

## 10. Test Results

After running tests, log the results:

```
POST /api/test-results
{
  "project_id": 1,
  "suite": "backend",
  "total_tests": 42,
  "passed": 40,
  "failed": 2,
  "skipped": 0,
  "duration_seconds": 8.3,
  "status": "failed",
  "triggered_by": "post-task",
  "details": "{\"failures\": [\"test_sync_check\", \"test_migration\"]}"
}
```

Query: `GET /api/test-results?project_id=1&suite=backend&status=failed`

---

## 11. Reading the Dashboard

The TL should regularly check:

1. **Open tickets by status** — are things moving through the pipeline?
   `GET /api/tickets?project_id=1&status=in_progress`

2. **Active sprint progress** — how many tickets done vs total?
   `GET /api/tickets?sprint_id={active_sprint_id}`

3. **Unresolved alerts** — anything blocking?
   `GET /api/alerts?project_id=1&status=open`

4. **Token usage** — are agents burning too many tokens?
   Check `tokens_used` on completed tickets. Update `tl_overhead_tokens` on the project.

5. **Test results** — are tests passing?
   `GET /api/test-results?project_id=1&limit=5`

---

## 12. TL Workflow — Typical Session

1. Check open alerts: `GET /api/alerts?status=open`
2. Review active sprint: `GET /api/tickets?sprint_id={id}&status=in_review`
3. Accept or return reviewed tickets
4. Create new tickets for next batch of work
5. Assign tickets to available agents
6. Set or update instructions as patterns emerge
7. Log activity for significant decisions
8. Update overhead tokens/time on the project

---

## Note: Auto-Loading Instructions

Consider loading agent-scoped instructions automatically when a TL agent starts a session. A startup script could:

1. `GET /api/instructions?scope=agent&agent_id={tl_agent_id}` — fetch TL-specific rules
2. `GET /api/instructions?scope=global` — fetch global rules
3. `GET /api/instructions?scope=project&project_id={id}` — fetch project rules

Inject these into the agent's system prompt or context. This ensures every session starts with the full rule set without the TL having to remember to check.
