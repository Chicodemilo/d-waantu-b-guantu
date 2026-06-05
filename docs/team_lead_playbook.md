# Team Lead Playbook

> Base URL: `http://localhost:8000`

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself. **The human user approves all ticket proposals before anything is created.**

## Canonical Tools

All ticket operations go through the D2J (DWB_2_JIRA) CLI. Don't hand-roll curl for ticket CRUD.

- **Query:** `dwb2jira report` — filterable Jira+DWB merged view. Defaults to assignee=you.
- **Create:** `dwb2jira create proposal.yaml` — YAML input, preview + approval gate, auto-sprint, auto-DWB twin.
- **Status change:** `dwb2jira ticket transition POR-KEY --to "Done" [--comment "..."]` — atomic dual-write (Jira + DWB).
- **Full reference:** `~/Dev/DWB_2_JIRA/README.md`.

---

## On Startup

1. Read this playbook, `.claude/project_rules_team_lead.md`, `HANDOFF.md`
2. Fetch the live team roster: `GET /api/projects/{project_id}/team` — the DB is authoritative, not a checked-in file
3. Read `ARCHITECTURE.md` / `README.md` only for cross-cutting work
4. Check open alerts (API + `ALERTS_PENDING.md`)
5. Jump to § 5 for the typical session flow

### Playbook locations

Deployed to each project's `.claude/` via the Deploy Playbooks button. Playbooks get overwritten on deploy; `project_rules_*.md` never are.

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
2. For empty repos: ask user for goals/constraints, then write `INITIAL.md`, `ARCHITECTURE.md`, `HANDOFF.md`
3. Create first epic, first sprint, assign agents (TL + PM + worker minimum) — agents go in the DB via `POST /api/agents` + `POST /api/project-agents`
4. Have PM check gates and raise alerts for gaps

The team roster lives in the DB. `HANDOFF.md` = session continuity — read on start, update on end. Naming conventions for new agents are in § Naming Convention below.

---

## 2. API Reference

| Action | Endpoint | Notes |
|--------|----------|-------|
| **Sprints** | | |
| Create sprint | `POST /api/sprints` | Required: `project_id`, `name`, `goal`, `sprint_number`, dates |
| Update sprint | `PATCH /api/sprints/{id}` | `planned` → `active` → `completed`. One active at a time |
| List sprints | `GET /api/sprints?project_id={pid}` | Filter `status=active` for hygiene checks |
| **Epics** | | |
| Create epic | `POST /api/epics` | Required: `project_id`, `name` |
| **Agents** | | |
| Register agent | `POST /api/agents` | Body REQUIRES `project_id` (since DWB-287). Roles: `team_lead`, `pm`, `developer`, `reviewer`, `specialist`. UNIQUE(project_id, name) enforced. |
| Assign to project | `POST /api/project-agents` | Body: `{ project_id, agent_id }` |
| List project agents | `GET /api/project-agents?project_id={pid}` | |
| **Tickets (non-creation ops)** | | |
| Query | `dwb2jira report` or `GET /api/tickets` | Use `dwb2jira report` for cross-system view. Legacy `ticket list` strips assignee — don't use. |
| Transition status | `dwb2jira ticket transition POR-KEY --to "..."` | Dual-write. Never PATCH `/api/tickets/{id}` status directly on linked tickets. |
| Assign | `PATCH /api/tickets/{id}` with `assigned_agent_id` | DWB-side only; Jira assignment is separate |
| **Creation** | | |
| New ticket(s) | `dwb2jira create proposal.yaml` | YAML input + approval gate. Never `POST /api/tickets` directly for new tickets. |
| **Comments** | | |
| Add | `POST /api/comments` | Body: `{ ticket_id, author_agent_id, body }` |
| List | `GET /api/comments?ticket_id={id}` | |
| **Alerts** | | |
| Raise | `POST /api/alerts` | Severities: `info`, `warning`, `critical` |
| Update | `PATCH /api/alerts/{id}` | `open` → `acknowledged` → `resolved` |
| List open | `GET /api/alerts?project_id={pid}&status=open` | |
| Dismiss all | `POST /api/alerts/dismiss-all` | Use after sprint close if queue is stale |
| **Activity Log** | | |
| Log event | `POST /api/activity-logs` | Body: `{ project_id, agent_id, entity_type, entity_id, action, details }` |
| Query | `GET /api/activity-logs?project_id={pid}` | Filters: `entity_type`, `limit` |
| **Test Results** | | |
| Log | `POST /api/test-results` | Body: `{ project_id, suite, total_tests, passed, failed, status, ... }` |
| Query | `GET /api/test-results?project_id={pid}` | Filters: `suite`, `status` |
| **Tracking** | | |
| Usage summary | `GET /api/tracking/summary?project_id={pid}` | Per-ticket/agent/sprint rollups (automatic via hooks) |
| Hook sessions | `GET /api/hooks/sessions?project_id={pid}` | |

---

## 3. Ticket Workflow

Status flow: `backlog` → `todo` → `in_progress` → `in_review` → `done`. Time/token tracking is automatic via lifecycle hooks.

### Creation flow

TL drafts a YAML proposal, Pam (PM) previews + shows human, human approves, Pam submits via `echo Y | dwb2jira create`. Creation atomic across Jira + DWB; human approves before anything exists.

### Querying

- Your work today: `dwb2jira report --status "To Do,In Progress,Ready for Testing/Review"`
- Last 2 weeks: `dwb2jira report --assignee '*' --updated ">=YYYY-MM-DD"`
- Single ticket: `dwb2jira report --jira POR-KEY`

Default `dwb2jira report` returns ALL statuses — add `--status` to filter. Status vocabulary: see `~/Dev/DWB_2_JIRA/README.md`.

### Bulk operations

Bulk ops are rare by design (`create` gate + dual-write tools prevent drift). If you hit a genuine need, propose the batch to the human first — don't hand-roll REST loops without approval.

### Duplicate cleanup

`dwb2jira create` warns on likely duplicates at preview. If you find existing dupes, pick the canonical one and `dwb2jira ticket delete POR-KEY` the others — the DWB twin deletes too.

### Sprint hygiene

Only one sprint should be `active` per project. Check at every transition:
```
GET /api/sprints?project_id={pid}&status=active
PATCH /api/sprints/{id} { "status": "completed" }   # close any stale ones
```

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

> **PM Jira authority is strictly read-only at the sprint level.** PMs cannot close/create/edit/delete Jira sprints — only DWB sprints. If you (the TL) need a Jira sprint operation, do it yourself with explicit human approval. See `docs/pm_playbook.md` § Safety — Hard Limits on Jira Manipulation.

---

## 5. TL Workflow — Typical Session

1. Check open alerts (`GET /api/alerts?status=open` + `ALERTS_PENDING.md`)
2. Review active sprint: `dwb2jira report --sprint active --status "Ready for Testing/Review"`
3. Accept or return reviewed tickets
4. Propose new tickets via YAML → `dwb2jira create --dry-run prop.yaml`, show preview to human
5. On approval: `echo Y | dwb2jira create prop.yaml` (or hand off to PM)
6. Assign tickets to agents (update `assigned_agent_id`)
7. Log significant decisions in the activity log
8. Check `GET /api/tracking/summary?project_id={pid}` for token outliers

---

## 5a. Sprint Close — Consolidation Gate (REQUIRED)

The TL is the final witness on the `force_consolidation` gate. The gate has TEETH (DWB-328): the ack endpoint REFUSES with HTTP 400 when an agent's owned files are over ceiling, unless per-file overrides with non-empty reasons are provided. Participant set is narrowed by DWB-326 (only agents with sprint signals — tickets, comments, tracking_log, hook_sessions, activity_log within window).

Before PATCHing a sprint to `completed`:

```bash
GET /api/projects/{pid}/consolidation-status?sprint_id={sid}
```

- If `gate_satisfied: true` — every participant acked. Safe to PATCH.
- If `gate_satisfied: false` — do NOT close. Walk the `agents[]` list, name every `acked: false`, ping with their `owned_over_ceiling_files`.

**TL self-ack with the same discipline as workers:** trim own files BEFORE acking. If your ack returns 400, that's the signal to TRIM the listed files, not to override. Override path is for genuinely load-bearing content; repeated overrides on the same file mean the cap is wrong — raise it in `_TOKEN_CEILINGS`.

**Autonomy expectation across the team (DWB-328 lesson):** refusal IS the signal to fix. Workers who get a 400 should trim and retry on their own without waiting for TL guidance. If a worker is idling on a refused ack, that's a worker-side process bug — message them with "trim is the work, not the wait." Don't accept "I tried, was refused, waiting" as a final state.

**TL admin acks** are for edge cases only — e.g. DWB-329 (participants_for_sprint counts admin-only activity_log entries as participation). Document the reason in the ack notes; don't normalize the pattern.

Marking an agent inactive removes them from the gate. Use only when an agent has actually gone dark, not as a workaround for chasing acks.

---

## 6. Naming Convention (for new agents)

Agent names are **unique system-wide** (single `UNIQUE(name)` constraint on `agents` table). When picking a name for a new agent, follow the pattern: match as many leading letters of the role as possible to a real human name. Three-letter matches are better than two.

**Fixed-role defaults** — the canonical name for these roles is the same across every project. Because the name field is system-wide-unique, the second project that needs one of these roles must suffix with `_<PROJECT_PREFIX>`:

| Role | Default | Cross-project pattern |
|------|---------|----------------------|
| team-lead | **Archie** | `Archie_DWB`, `Archie_D2J`, `Archie_CI` |
| pm | **Pam** | `Pam_DWB`, `Pam_CI`, … |
| tester | **Chester** or **Sage** | `Sage_DWB`, `Chester_D2J`, … |

**Worker-role defaults** — each project usually has at most one, so suffix only on collision:

| Role | Default |
|------|---------|
| frontend-worker | **Freddie** or **Pixel** |
| backend-worker | **Barry** or **Devin** |
| system-ops | **Sylvie** (or Bolt, deprecated on DWB) |

**Custom roles** — same leading-letter pattern:

| Role | Example names |
|------|--------------|
| designer | **Des**mond, **Des**iree |
| researcher | **Res**a, **Re**my |
| devops | **Dev**on, **Dev**in |
| analyst | **Ana**stasia, **An**dre |
| reviewer | **Rev**a, **Re**ggie |
| security | **Sec**ily, **Seb**astian |
| database | **Da**rcy, **Dan**te |
| architect | **Arc**hie, **Ari**adne |
| mobile | **Mo**ira, **Mor**ris |
| docs-writer | **Dol**ores, **Dom**inic |
| data-engineer | **Da**phne, **Dan**iel |
| infra | **Ing**rid, **Irv**ing |
| qa | **Qu**inn |
| ux | **Ur**sula |
| api-worker | **Apr**il |
| migrator | **Mi**tch, **Min**a |
| performance | **Per**cy, **Pet**ra |
| scheduler | **Sca**rlett |

If you spawn a role not listed here, follow the pattern: 3-letter prefix > 2-letter. If the name already exists on another project, suffix with `_<PROJECT_PREFIX>`.

The `role` field in the DB maps to the Claude teammate name (e.g., `role="pm"` → `@pm`). The `name` field is the unique display identity.

**Live roster:** the team for any project is at `GET /api/projects/{project_id}/team`. The roster is DB-authoritative — no checked-in TEAM.md file.
