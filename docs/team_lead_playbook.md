# Team Lead Playbook

> Base URL: `http://localhost:8000`

## On Startup

1. Read this playbook, `.claude/project_rules_team_lead.md`, `HANDOFF.md`, `TEAM.md`
2. Read `ARCHITECTURE.md` / `README.md` only for cross-cutting work
3. Check open alerts (API + `ALERTS_PENDING.md`)

---

## 1. Project Setup

| Action | Endpoint | Notes |
|--------|----------|-------|
| Create from repo | `POST /api/projects/from-repo` | Body: `{ "repo_path": "..." }` — auto-populates from repo metadata |
| Create manually | `POST /api/projects` | Required: `prefix`, `name`, `description`. Optional: `repo_path`, `status` |
| Update project | `PATCH /api/projects/{id}` | |
| Check gates | `GET /api/projects/{id}/gate-status` | Shows which doc gates pass/fail |

### First-Run Checklist (New Projects)

1. Check gate status — handle failures
2. For empty repos: ask user for goals/constraints, then write `INITIAL.md`, `ARCHITECTURE.md`, `TEAM.md`, `HANDOFF.md`
3. Create first epic, first sprint, assign agents (TL + PM + worker minimum)
4. Update `TEAM.md` with spawned workers
5. Have PM check gates and raise alerts for gaps

`TEAM.md` = live roster at repo root. `HANDOFF.md` = session continuity — read on start, update on end.

---

## 2. API Reference

| Action | Endpoint | Notes |
|--------|----------|-------|
| **Sprints** | | |
| Create sprint | `POST /api/sprints` | Required: `project_id`, `name`, `goal`, `sprint_number`, dates |
| Update sprint | `PATCH /api/sprints/{id}` | Statuses: `planned` -> `active` -> `completed`. One active at a time |
| List sprints | `GET /api/sprints?project_id={id}` | |
| **Epics** | | |
| Create epic | `POST /api/epics` | Required: `project_id`, `name` |
| **Agents** | | |
| Register agent | `POST /api/agents` | Roles: `team_lead`, `pm`, `developer`, `reviewer`, `specialist` |
| Assign to project | `POST /api/project-agents` | Body: `{ project_id, agent_id }` |
| List project agents | `GET /api/project-agents?project_id={id}` | |
| **Tickets** | | |
| Create ticket | `POST /api/tickets` | Required: `project_id`, `ticket_number`, `ticket_key`, `title`, `status` |
| Update ticket | `PATCH /api/tickets/{id}` | |
| Query tickets | `GET /api/tickets` | Filters: `project_id`, `sprint_id`, `assigned_agent_id`, `status` — combinable |
| **Comments** | | |
| Add comment | `POST /api/comments` | Body: `{ ticket_id, author_agent_id, body }` |
| List comments | `GET /api/comments?ticket_id={id}` | |
| **Alerts** | | |
| Raise alert | `POST /api/alerts` | Severities: `info`, `warning`, `critical` |
| Update alert | `PATCH /api/alerts/{id}` | Statuses: `open` -> `acknowledged` -> `resolved` |
| List open alerts | `GET /api/alerts?project_id={id}&status=open` | |
| Dismiss all | `POST /api/alerts/dismiss-all` | Use after sprint close if queue is stale |
| **Activity Log** | | |
| Log event | `POST /api/activity-logs` | Body: `{ project_id, agent_id, entity_type, entity_id, action, details }` |
| Query log | `GET /api/activity-logs?project_id={id}` | Filters: `entity_type`, `limit` |
| **Test Results** | | |
| Log results | `POST /api/test-results` | Body: `{ project_id, suite, total_tests, passed, failed, status, ... }` |
| Query results | `GET /api/test-results?project_id={id}` | Filters: `suite`, `status` |
| **Tracking** | | |
| Usage summary | `GET /api/tracking/summary?project_id={id}` | Per-ticket, per-agent, per-sprint rollups (automatic via hooks) |
| Hook sessions | `GET /api/hooks/sessions?project_id={id}` | |

---

## 3. Ticket Workflow

Status flow: `backlog` -> `todo` -> `in_progress` -> `in_review` -> `done`

The TL moves tickets through this pipeline. Assign via `assigned_agent_id`. Time/token tracking is automatic via lifecycle hooks.

### Required table format for proposed tickets

When proposing tickets (sprint kickoff, mid-sprint changes, close-out reports), always use this format:

| DWB Ticket | Jira Ticket | DWB Sprint | Jira Epic | Jira Sprint | Title | Proposed Status | Current Status |
|------------|-------------|------------|-----------|-------------|-------|-----------------|----------------|
| CI-105 | POR-??? | Sprint 4 | POR-5152 | We Are Dashboard | Example task title | todo | — |

- **Proposed Status** — status to create at or move to (`backlog`, `todo`, `in_progress`, `in_review`, `done`, `cancelled`)
- **Current Status** — actual status now. Use `—` for new tickets. Shows delta between current and proposed state.

---

## 4. Alert Triage

Check alerts at natural breakpoints: after closing tickets, when agents go idle, at sprint transitions, when the human sends a message.

### ALERTS_PENDING.md

If `.claude/ALERTS_PENDING.md` exists, **read it immediately — it takes priority.** Written by the human via "Send Alerts to Team" button. Contains alerts requiring immediate action. File auto-deletes when all alerts are resolved/dismissed. Handle before the API alert queue.

### Triage table

| Alert Type | Examples | Action |
|------------|----------|--------|
| Simple / self-service | Stale ticket (agent confirmed dead), zero-token no-op | Handle directly — move ticket, dismiss alert, comment |
| Needs investigation | Unclear stale ticket, unexpected failure, gate failure | Delegate to PM |
| Critical / human decision | DB errors, agent loop, scope questions, compliance | Escalate to human |

Don't let open alerts accumulate — an ignored queue trains everyone to ignore alerts.

---

## 5. TL Workflow — Typical Session

1. Check open alerts (`GET /api/alerts?status=open` + `ALERTS_PENDING.md`)
2. Review active sprint: `GET /api/tickets?sprint_id={id}&status=in_review`
3. Accept or return reviewed tickets
4. Create and assign new tickets for next batch of work
5. Log activity for significant decisions
6. Check tracking summary: `GET /api/tracking/summary?project_id={id}`
