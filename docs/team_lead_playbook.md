# Team Lead Playbook

> How a Team Lead agent operates inside D'Waantu B'Guantu.
> Base URL: `http://localhost:8000`

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. It is NOT visible to external stakeholders.

- **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content
- **Never reference DWB ticket IDs** (e.g., "DWB-234") outside of DWB itself
- **Jira is the external system** — if a project has Jira integration, Jira tickets are what stakeholders see. DWB tracks the internal agent workflow behind those tickets.
- **The human user approves all ticket proposals** — present proposed tickets in the required table format and wait for approval before creating them in DWB or Jira

## Playbook Locations

Deployed to each project's `.claude/` directory via the Deploy Playbooks button:

| File | Path | Overwritten on deploy? | Purpose |
|------|------|----------------------|---------|
| TL Playbook | `.claude/team_lead_playbook.md` | Yes | Generic TL operating procedures |
| PM Playbook | `.claude/pm_playbook.md` | Yes | Generic PM operating procedures |
| Worker Playbook | `.claude/worker_playbook.md` | Yes | Generic rules for all agents |
| TL Project Rules | `.claude/project_rules_team_lead.md` | **No** | Project-specific TL rules |
| PM Project Rules | `.claude/project_rules_pm.md` | **No** | Project-specific PM rules |
| Worker Project Rules | `.claude/project_rules_worker.md` | **No** | Project-specific worker rules |

Playbooks are generic — they get overwritten on every deploy. Project rules are project-specific — they're created blank on first deploy and never overwritten.

Re-deploy: `POST /api/projects/{id}/deploy-playbooks` or the Deploy Playbooks button on the project page.

### On Startup

Read these files at session start:
1. This playbook (`.claude/team_lead_playbook.md`)
2. Your project rules (`.claude/project_rules_team_lead.md`)
3. `HANDOFF.md` — session continuity
4. `TEAM.md` — current roster

Read `ARCHITECTURE.md` and `README.md` only when doing cross-cutting work that spans multiple systems.

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
  "repo_path": "/Users/mchick/Dev/d-waantu_b-guantu"
}
```

Fields that matter:
- `prefix` — short uppercase tag (max 6 chars), used to generate ticket keys (e.g. `DWB-001`)
- `repo_path` — optional filesystem path to the repo, useful for test runners and scripts
- `status` — one of `active`, `paused`, `completed`, `archived`. Default: `active`

Update with `PATCH /api/projects/{id}`.

---

## 1b. First-Run Checklist (New Projects)

After creating a project, immediately:

### Check gate status
```
GET /api/projects/{id}/gate-status
```

This returns which documentation gates are passing or failing. Gates enabled by default: `force_initial_md`, `force_architecture_md`, `force_team_md`, `force_handoff_md`.

### Handle empty repos
If the repo is empty or has no meaningful structure:
1. Ask the user: *"What is this project? What's the goal? What are the constraints?"*
2. Update the project with their answers: `PATCH /api/projects/{id}` (description, name)
3. Write `INITIAL.md` at the repo root covering: why, requirements, phases, design decisions, constraints, success criteria
4. Write `ARCHITECTURE.md` once the system design is decided
5. Write `TEAM.md` using the template (`.claude/agents/TEAM.md.template`) — start with Archie + Pam, add workers as you spawn them
6. Write `HANDOFF.md` — initial session state, decisions, gotchas

### TEAM.md — Live Roster
`TEAM.md` is the live team roster at the project repo root. It starts with mandatory agents (Archie + Pam) and grows as you spin up workers. Update it when the team composition changes. Agent naming conventions live here — not in the TL playbook.

### HANDOFF.md — Session Continuity
`HANDOFF.md` carries context from session to session. Read it at the start of every session. Update it at the end with: current state, new decisions, gotchas, and a brief summary of what happened.

### Create initial structure
1. Create the first epic: `POST /api/epics` — name it after the first major milestone
2. Create the first sprint: `POST /api/sprints` — set a goal, assign a start/end date
3. Assign agents to the project: `POST /api/project-agents` — at minimum, assign TL, PM, and one worker
4. Update `TEAM.md` with the workers you spawned
5. Have the PM check gate status and raise alerts for anything missing

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

### Required table format for proposed tickets

When proposing tickets (sprint kickoff, mid-sprint changes, close-out reports), always present them in this table format:

| DWB Ticket | Jira Ticket | DWB Sprint | Jira Epic | Jira Sprint | Title | Proposed Status | Current Status |
|------------|-------------|------------|-----------|-------------|-------|-----------------|----------------|
| CI-105 | POR-??? | Sprint 4 | POR-5152 | We Are Dashboard | Example task title | todo | — |
| CI-??? | POR-??? | Sprint 4 | POR-5152 | We Are Dashboard | Another task | todo | — |

**Column definitions:**
- **Proposed Status** — the status the ticket should be created at or moved to. One of: `backlog`, `todo`, `in_progress`, `in_review`, `done`, `cancelled`.
- **Current Status** — the ticket's actual status right now. Use `—` for tickets that don't exist yet. This column lets Miles see the delta between where things are and where the TL wants them to be.

**When to use each:**
- **Sprint kickoff proposals** — Proposed Status = `todo` (or `done` for retroactive tickets), Current Status = `—`
- **Mid-sprint status updates** — Proposed Status = what you want to change it to, Current Status = what it is now
- **Sprint close-out reports** — Proposed Status = `done`, Current Status = actual status (flags anything not finished)

### Assigning work
Set `assigned_agent_id` when creating or updating a ticket. An unassigned ticket has `null` for this field.

### Tracking effort — AUTOMATIC

Time and token tracking is fully passive via Claude Code lifecycle hooks. See CLAUDE.md for how attribution works. Check current state:
- `GET /api/tracking/summary?project_id=1` — per-ticket, per-agent, per-sprint rollups
- `GET /api/hooks/sessions?project_id=1` — active/recent hook sessions

### Querying tickets
- By project: `GET /api/tickets?project_id=1`
- By sprint: `GET /api/tickets?sprint_id=1`
- By agent: `GET /api/tickets?assigned_agent_id=3`
- By status: `GET /api/tickets?status=in_progress`
- Combine filters: `GET /api/tickets?project_id=1&status=todo&sprint_id=1`

---

## 6. Comments

Add context to tickets. Use for status updates, review notes, questions.

```
POST /api/comments
{
  "ticket_id": 5,
  "author_agent_id": 1,
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

## 8b. Alert Triage at Natural Cadence Points

Checking open alerts is a core TL duty — not a scheduled task, but something woven into your natural workflow rhythm.

### When to check

Check `GET /api/alerts?project_id={pid}&status=open` **and** check if `.claude/ALERTS_PENDING.md` exists at these natural breakpoints:

1. **After accepting or closing a ticket** — you just freed up capacity, check if anything needs attention
2. **When a teammate goes idle** with no immediate work to assign — use the downtime to scan for problems
3. **At sprint transitions** — before opening or closing a sprint, clear the alert queue
4. **When the human sends a new message** — check before responding so you have full situational awareness

### ALERTS_PENDING.md (human-flagged alerts)

If `.claude/ALERTS_PENDING.md` exists at the project repo root, **read it immediately — it takes priority over the API alert queue.** This file is written by the human via the "Send Alerts to Team" button on the project page. It contains specific alerts the human wants you to act on now.

- Read the file and act on each listed alert
- The file auto-deletes when all alerts in it are resolved or dismissed
- If the file exists, handle its contents before moving to the API alert queue

### How to triage

| Alert Type | Examples | Action |
|------------|----------|--------|
| Simple / self-service | Stale ticket (agent confirmed dead), zero-token warning on a no-op ticket | Handle directly — move ticket, dismiss alert, leave a comment |
| Needs investigation | Stale ticket (unclear if agent is alive), unexpected failure record, gate failure | Delegate to PM — ask Pam to investigate and report back |
| Critical / human decision | DB errors, agent stuck in loop, scope questions, compliance issues | Escalate to the human via alert + direct message |

### What alert types surface here

This catches everything the system and PM raise:
- **Stale ticket alerts** — in_progress too long with no activity
- **Zero-token warnings** — ticket closed with 0 tokens (hook misconfiguration or no-op)
- **Failure record stubs** — rework detected, PM needs to classify
- **Gate failures** — missing docs, no test run
- **PM-raised warnings** — blockers, scope questions, agent issues
- **Sprint health flags** — burndown off track, pileup in one status

### After triaging

- **Acknowledge** alerts you've seen and are handling: `PATCH /api/alerts/{id} { "status": "acknowledged" }`
- **Resolve** alerts that are dealt with: `PATCH /api/alerts/{id} { "status": "resolved" }`
- **Dismiss all** if the queue is stale after a sprint close: `POST /api/alerts/dismiss-all`

Don't let open alerts accumulate — an ignored alert queue trains everyone to ignore alerts.

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
   `GET /api/tracking/summary?project_id=1` — shows per-ticket, per-agent, per-sprint rollups. Tracked automatically via hooks.

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
8. Check tracking summary: `GET /api/tracking/summary?project_id=1` (time + tokens captured automatically via hooks)

