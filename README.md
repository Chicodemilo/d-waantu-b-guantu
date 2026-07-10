# D'Waantu B'Guantu (DWB)

A multi-agent workflow dashboard for Claude Code teams: ticket tracking, token accounting, and session continuity for a roster of agents.

- **Token efficiency:** structured playbooks and slim API responses keep agent context spent on work, and budget monitoring warns when context files grow past their ceilings.
- **Team visibility:** see what every agent is doing, which tickets are moving, and where things are stuck.
- **Session continuity:** HANDOFF.md, playbooks, and project rules carry knowledge between sessions.

**Contributing:** DWB is open source. If something is broken or could work better, open a PR.

---

## Quick Start

```bash
git clone https://github.com/your-org/d-waantu-b-guantu.git
cd d-waantu-b-guantu
claude
```

Then paste:

```
You are Archie, the Team Lead. You report to me. Read this repo. It's
D'Waantu B'Guantu, our project management system. We'll be using it to
track our projects. Do the quick start setup and report back when
running.
```

Archie reads the repo, runs setup, creates your first project, and reports back. See [QUICKSTART.md](QUICKSTART.md) for manual setup.

---

## Architecture

```
React UI (Vite/5173) ──▶ FastAPI (:8000) ──▶ MySQL 8 (:23847)
```

- **Backend:** FastAPI, SQLAlchemy 2.0, Pydantic v2; routers → services → models, Alembic migrations.
- **Frontend:** React 18, Vite, Zustand, React Router; plain CSS, dark terminal aesthetic (JetBrains Mono); adaptive polling 2s/10s.
- **Database:** MySQL 8.0 via Docker (PyMySQL).

---

## Core Concepts

### Hierarchy

```
Project → Epic → Sprint → Ticket
```

Enforced at the API: every ticket needs a sprint, every sprint an epic, every epic a project. Missing parents return 400.

**Auto-assignment:** Tickets without `sprint_id` get the active sprint and inherit its epic; sprints without `epic_id` get the latest open epic.

### Agents & Teams

Agent definitions in `.claude/agents/` auto-load when spawning teammates. Minimum team: `@team-lead` + `@pm`. Add `@frontend-worker`, `@backend-worker`, `@system-ops`, `@tester` as needed.

Agents are assigned to projects via `project_agents`. The `X-Agent-ID` header on mutating requests attributes actions in the activity feed.

**Per-project rows + system-wide unique names** (DWB-287, 315). Each agent row has one `project_id`; `agents.name` is `UNIQUE` system-wide. Fixed-role agents recurring on every project (TL, PM) get a `_<PREFIX>` suffix (`Archie_DWB`); workers stay plain until a collision. Identify accepts either form.

**Spawn-time identity flow.** A teammate calls `POST /api/agents/identify` for its `agent_id` and memory dir. Subagent token attribution uses a pending-marker scheme the TL writes at spawn; details in [ARCHITECTURE.md](ARCHITECTURE.md) § 5.

### Team Status

The LiveSessions panel on each project page shows assigned agents with real-time status (active when holding an `in_progress` ticket) and a score leaderboard. Elapsed time ticks from the ticket's `updated_at`.

**Stale detection:** a frontend timer fires `POST /api/tickets/stale-check` when an in_progress ticket crosses a 10-min boundary, raising a deduped alert.

### Deployable Playbooks

Master playbooks in `docs/` deploy to other repos via `POST /api/projects/{id}/deploy-playbooks`; the project page shows last deploy time (`playbooks_deployed_at`).

| Playbook | File |
|----------|------|
| Team Lead | `docs/team_lead_playbook.md` |
| PM | `docs/pm_playbook.md` |
| Worker | `docs/worker_playbook.md` |

---

## Tracking (Time & Tokens)

The `tracking_log` table is the source of truth, recording discrete events: `start`, `stop`, `token_report`, `overhead_start`, `overhead_stop`.

**Time:** start/stop event pairs per ticket; status transitions auto-insert them (e.g., moving to `in_progress` logs a `start`).

**Tokens:** captured passively via Claude Code lifecycle hooks: `SessionStart` → `/api/hooks/session-start` (logs start); `SessionEnd` → `/api/hooks/session-end` (parses JSONL, logs stop + tokens, increments `ticket.tokens_used`); `SubagentStop` → same endpoint for teammate transcripts.

**Attribution priority:** Workers get tokens on their active ticket: `in_progress` > `todo` > `in_review` > recently `done` (5 min). Unmatched TL/PM sessions go to project overhead (`tl_overhead_tokens`, `pm_overhead_tokens`). Hook config lives in `.claude/settings.json` and runs without manual steps.

**Overhead:** TL/PM coordination tracks at project level via `overhead_start`/`overhead_stop` into per-role buckets; `GET /api/tracking/summary` `per_agent` rows carry a `tokens` total plus a separate `overhead_tokens`.

Hooks handle backfill and recovery automatically; no separate scan script is needed.

---

## DWB Sessions

A DWB session is a user-bounded span of work: it opens when you signal start, closes when you signal stop, and rolls up tokens + wall-clock time across every CC session in between (one DWB session spans many). Single-active per project, DB-enforced. Four detection layers (Layer-2 Haiku retired, DWB-402): regex on open/close phrases, a SessionEnd transcript retry, slash commands (`/dwb-open`/`/dwb-close`), and a 60-min idle sweeper. Full reference: [docs/session_lifecycle.md](docs/session_lifecycle.md).

---

## Sprint Gates

Boolean toggles gating sprint completion. All default OFF (opt-in per project):

| Toggle | Check |
|--------|-------|
| `force_test_run` | Test run recorded during sprint |
| `force_test_coverage` | Every router has a test file |
| `force_initial_md` | `INITIAL.md` exists at repo root |
| `force_architecture_md` | `ARCHITECTURE.md` exists at repo root |
| `force_handoff_md` | `HANDOFF.md` exists at repo root |
| `force_consolidation` | TL-owned docs within token ceiling; agent memory exempt |
| `force_headers` | Sprint-touched `.py` files carry the code-header block; missing ones block close |
| Failure records | Unreviewed stubs always block close |

Check gates: `GET /api/projects/{id}/gate-status`

On sprint completion: alerts fire to TL/PM/tester, test ticket auto-created for next sprint.

---

## Failure Analysis

**Auto-detected:** ticket back to `in_progress` after `done` → rework record + PM alert; failed test → one record per failed test.

**Manual taxonomy:** types A–G, categorized by the PM. Unreviewed stubs block sprint close. Summary: `GET /api/failure-records/summary`.

---

## Agent Scoring

Each agent earns a score per project, shown as a leaderboard on the project page. Two currencies: **reputation** (all-time rank, driven by deterministic signals: ticket closes + no-rework bonus, minus rework, test failures, stale tickets, zero-token closes, gate misses) and **influence** (a per-sprint budget, default 20, spent to praise/dock peers; ledger-derived, resets each sprint). An append-only `score_event` ledger is the source of truth; `agent_score` is a rebuildable cache. Every change carries a reason and is reversible.

**Human tools** (free): `/carrot`, `/stick`, `/score`, `/leaderboard`. **Peer economy** is flat: any agent can carrot/stick any other; only self-scoring is barred (caps in `config/scoring.py`). Human and peer carrot/sticks broadcast to all project agents (human at critical severity); auto-triggers do not. Per-agent ledger on the AgentPage.

---

## Archie Channel

A cross-project channel for team-leads to message each other, direct (one TL) or broadcast (all). Every TL sees every message; addressing drives the ping only (direct alerts the target, broadcast the other TLs). Unread surfaces atop a TL's `identity.md` on spawn, marked read once shown. Reply via `/tl`. Tables: `tl_messages` + `tl_message_reads` (not project-scoped).

---

## Inter-Agent Comms

Native Claude Code SendMessage traffic is captured per project (DWB-446..449): a `PostToolUse` hook posts each message to `POST /api/hooks/agent-message`, where the sender resolves from the CC `session_id` and the recipient best-effort by name (bodies are stored: agent text). The `/projects/:id/comms` page lists them newest-first with a clear-all. Per-project `capture_agent_comms` (default ON) gates capture; rows older than 4 days are purged. Table: `inter_agent_messages`.

---

## Alerts

Alerts are flags raised by agents or automation that need human attention. Severities: info, warning, critical.

**Dashboard:** read-only table (Project, Severity, Title, Created).

**Project page:** full alert cards with actions: `$ dismiss all` (bulk dismiss open alerts) and `$ send to team` (writes `ALERTS_PENDING.md` to the project repo for teammates).

---

## Jira Integration

Projects can optionally link to Jira: one DWB ticket = one Jira issue (1:1 via `jira_issue_key`). Enable/disable via the Tools panel; disabling clears all Jira links (Jira is never modified).

- Enable: `PATCH /api/projects/{id}` with `jira_project_key` and `jira_base_url`
- Disable: `POST /api/projects/{id}/disable-jira`

---

## Error Logging

The frontend reports errors via `POST /api/errors`; the client auto-captures failed requests (endpoint, status, message, stack). View: `GET /api/errors`.

---

## Testing

```bash
cd backend && pytest tests/                                           # local
./backend/scripts/run_tests.sh --post --project-id 1 --triggered-by "manual"   # with API reporting
```

Or trigger via API: `POST /api/system/run-tests`

Coverage check: `GET /api/status/test-coverage`
Run history: `GET /api/test-results/performance`

---

## Adding a Project

**Demo:** `POST /api/projects/seed-demo` creates a fully-populated demo (prefix `DMO`) with agents, epics, sprints, tickets, and test results. Idempotent.

**From repo:** `POST /api/projects/from-repo` with `{"repo_path": "..."}` auto-detects name, prefix, and description.

**Then:** assign agents, create epic + sprint (with a goal), deploy playbooks, tickets.

---

## API Reference

138 endpoints across 23 routers. Full interactive docs at http://localhost:8000/docs.

**Slim responses:** List endpoints strip heavy fields by default (test-results omit `details`, agents omit `api_key`); tickets/alerts/sprints support `?fields=slim`.

Standard CRUD exists for all resources; the non-obvious and automation ones:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects/from-repo` | Create project from repo scan |
| POST | `/api/projects/seed-demo` | Seed demo project (idempotent) |
| POST | `/api/projects/{id}/deploy-playbooks` | Deploy playbooks to project repo |
| POST | `/api/projects/{id}/disable-jira` | Disable Jira, clear all issue links |
| GET | `/api/projects/{id}/gate-status` | Check sprint gates |
| GET | `/api/projects/{id}/activity-feed` | Activity feed (newest first) |
| GET | `/api/projects/{id}/docs` | Scan project doc files |
| GET | `/api/projects/{id}/token-budget` | Context file token counts + ceilings |
| POST | `/api/tickets/stale-check` | Stale ticket alert (frontend timer) |
| GET | `/api/tracking/summary` | Project tracking summary (tracking ops under `/api/tracking/*`) |
| POST | `/api/hooks/session-start` | Receive SessionStart hook |
| POST | `/api/hooks/session-end` | Receive SessionEnd/SubagentStop hook |
| POST | `/api/hooks/tool-use` | PostToolUse action capture (fire-and-forget) |
| POST | `/api/hooks/lifecycle-event` | Notification / PreCompact capture |
| POST | `/api/hooks/agent-message` | Capture an inter-agent SendMessage (fire-and-forget) |
| GET | `/api/projects/{id}/agent-messages` | Captured inter-agent message log (newest first) |
| DELETE | `/api/projects/{id}/agent-messages` | Clear all captured messages (returns count) |
| GET | `/api/projects/{id}/scores` | Scoring leaderboard |
| POST | `/api/projects/{id}/scores/award` | Human carrot/stick |
| POST | `/api/projects/{id}/scores/peer` | Peer carrot/stick (`X-Agent-ID` header) |
| GET | `/api/tl-channel` | Cross-project team-lead channel; each message carries a `read_by` roster |
| GET | `/api/tl-channel/unread` | A team-lead's unread channel messages (`?agent_id`) |
| POST | `/api/tl-channel` | Send a channel message, direct or broadcast (TL only) |
| POST | `/api/tl-channel/mark-read` | Mark channel messages read (one or all) |
| GET | `/api/hooks/sessions` | List hook sessions (`status=orphan` for cleanup) |
| POST | `/api/sessions/open` | Open a DWB session; omit `opened_at` (server-stamped) |
| POST | `/api/sessions/{id}/close` | Close a DWB session; `headline` required on AI methods (422 otherwise); consolidation gate opt-in (`force_consolidation`, default OFF), TL-owned docs only |
| GET | `/api/projects/{id}/sessions` | List DWB sessions, most recent first |
| GET | `/api/sessions/{id}` | DWB session detail rollup (by_role/by_ticket/overhead) |
| POST | `/api/agents/identify` | Resolve identity from `(role, name, project_prefix)`; short or `_<PREFIX>` form |
| POST | `/api/agents/spawn-prepare` | Identify + return ready-to-paste spawn-brief markdown |
| POST | `/api/agents/{id}/session-complete` | Append the session-end block to `memory.md` |
| POST | `/api/agents/{id}/memory/append` | Append to `memory.md` (`file=memory`; append-only) |
| POST | `/api/agents/{id}/memory/compact` | Replace `memory.md` (compacted); over-ceiling triggers a passive trim |
| POST | `/api/agents/{id}/scaffold-memory` | Idempotently scaffold `.dwb/memory/` (identity.md + memory.md) |
| GET | `/api/projects/{id}/team` | Single-roundtrip team roster |
| POST | `/api/alerts/dismiss-all` | Bulk dismiss open alerts |
| POST | `/api/alerts/send-to-team` | Write alerts to ALERTS_PENDING.md |
| GET | `/api/tokens/audit` | Token usage audit |
| GET | `/api/failure-records/summary` | Aggregated failure analysis |
| GET | `/api/status` | Health check |
| POST | `/api/system/run-tests` | Trigger test suite |

---

## Configuration

See `.env.example` for all variables. Key settings:

| Variable | Default | Notes |
|----------|---------|-------|
| `MYSQL_PORT` | `23847` | Docker-mapped MySQL port |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Frontend API base |
| `PMA_PORT` | `8080` | phpMyAdmin port |
