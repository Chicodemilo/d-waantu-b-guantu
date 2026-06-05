# D'Waantu B'Guantu (DWB)

A multi-agent workflow dashboard that makes Claude Code teams **cheaper, clearer, and smarter**.

- **Token efficiency** — structured playbooks and slim API responses mean agents spend context on work, not re-reading docs. Token budget monitoring warns before bloat creeps in.
- **Team visibility** — real-time insight into what every agent is doing, which tickets are moving, and where things are stuck.
- **Session continuity** — HANDOFF.md, playbooks, and project rules carry knowledge between sessions. New sessions pick up where the last one left off.

**Contributing** — DWB is open source. If something's broken, inefficient, or could be better, open a PR. No process ceremony — just make it better.

---

## Quick Start

```bash
git clone https://github.com/your-org/d-waantu-b-guantu.git
cd d-waantu-b-guantu
claude
```

Then paste:

```
You are Archie, the Team Lead. You report to me. Read this repo — it's
D'Waantu B'Guantu, our project management system. We'll be using it to
track our projects. Do the quick start setup and report back when it's
running.
```

Archie reads the repo, runs the setup, creates your first project, and reports back ready for work. See [QUICKSTART.md](QUICKSTART.md) for manual setup and agent onboarding.

---

## Architecture

```
React UI (Vite/5173) ──▶ FastAPI (:8000) ──▶ MySQL 8 (:23847)
```

- **Backend** — FastAPI, SQLAlchemy 2.0, Pydantic v2. Three-layer: routers → services → models. 19 router files, 112 endpoints, 18 tables. Alembic migrations.
- **Frontend** — React 18, Vite, Zustand, React Router. Plain CSS with dark terminal aesthetic (JetBrains Mono). Adaptive polling: 2s active, 10s idle.
- **Database** — MySQL 8.0 via Docker. PyMySQL driver.

---

## Core Concepts

### Hierarchy

```
Project → Epic → Sprint → Ticket
```

Enforced at the API level — every ticket needs a sprint, every sprint an epic, every epic a project. Missing parents return 400.

**Auto-assignment:** Tickets without `sprint_id` get the active sprint. Tickets without `epic_id` inherit from the sprint. Sprints without `epic_id` get the latest open epic.

### Agents & Teams

Agent definitions in `.claude/agents/` auto-load when spawning teammates. Minimum team: `@team-lead` + `@pm`. Add `@frontend-worker`, `@backend-worker`, `@system-ops`, `@tester` as needed.

Agents are assigned to projects via `project_agents`. The `X-Agent-ID` header on mutating requests attributes actions in the activity feed.

**Per-project rows + system-wide unique names** (DWB-287, 2026-06-03; DWB-315, 2026-06-05). Every agent row carries `project_id` (a single project, no shared roster) and `agents.name` is `UNIQUE` across the whole system. Fixed-role agents that naturally recur on every project — TL, PM, occasionally tester — are stored with a `_<PROJECT_PREFIX>` suffix so they don't collide: `Archie_DWB`, `Pam_DWB`, `Archie_D2J`. Worker names (Devin, Pixel, Barry, Sylvie) stay plain until a real cross-project collision forces a rename. The identify endpoint accepts either the short name or the suffixed form, so spawn briefs continue to call `{name: "Archie", project_prefix: "DWB"}` and resolve correctly.

**Spawn-time identity flow.** When a teammate starts a session it calls `POST /api/agents/identify` to get its `agent_id` and memory dir. Before spawning, the TL writes a **pending marker** at `.claude/agents/active/pending-<agent_id>-<unix_ms>-<rand4hex>` with JSON content `{"agent_id": N, "agent_name": "...", "role": "...", "project_prefix": "DWB"}`. When the first SubagentStop hook fires, the resolver scans for the oldest unconsumed pending marker on this project and atomically renames it to the CC `session_id`. From that point on tokens land correctly on the named agent. See DWB-294 (marker authority) and DWB-304 (pending scheme + atomic rename).

### Team Status

The LiveSessions panel on each project page shows all assigned agents with real-time status. Agents appear active when they have an `in_progress` ticket. Elapsed time ticks from the ticket's `updated_at` timestamp.

**Stale ticket detection:** A frontend timer checks every second. When an in_progress ticket crosses a 10-minute boundary (10m, 20m, 30m...), it fires `POST /api/tickets/stale-check` which creates an alert. Thresholds are tracked per-session to prevent duplicate alerts.

### Deployable Playbooks

Master playbooks in `docs/` deploy to other project repos via `POST /api/projects/{id}/deploy-playbooks`. The project page shows the last deploy time from `playbooks_deployed_at`.

| Playbook | File |
|----------|------|
| Team Lead | `docs/team_lead_playbook.md` |
| PM | `docs/pm_playbook.md` |
| Worker | `docs/worker_playbook.md` |

---

## Tracking (Time & Tokens)

The `tracking_log` table is the source of truth. It records discrete events: `start`, `stop`, `token_report`, `overhead_start`, `overhead_stop`.

**Time** — start/stop event pairs per ticket. Status transitions auto-insert tracking events (e.g., moving to `in_progress` logs a `start`).

**Tokens** — captured passively via Claude Code lifecycle hooks:
- `SessionStart` → `POST /api/hooks/session-start` → creates hook session, logs start
- `SessionEnd` → `POST /api/hooks/session-end` → parses JSONL transcript, logs stop + tokens, increments `ticket.tokens_used`
- `SubagentStop` → same endpoint for teammate transcripts

**Attribution priority:** Workers get tokens on their active ticket: `in_progress` > `todo` > `in_review` > recently `done` (5 min window). Unmatched TL/PM sessions go to project overhead fields (`tl_overhead_tokens`, `pm_overhead_tokens`).

Hook config lives in `.claude/settings.json`. Zero manual intervention needed.

**Overhead** — TL/PM coordination time tracked at the project level via `overhead_start`/`overhead_stop` events. Tokens land in per-role buckets: `projects.tl_overhead_tokens` for the team-lead and `projects.pm_overhead_tokens` for the PM (DWB-305, 2026-06-05). Both buckets are computed from `tracking_log.event_type='overhead_token_report'` rows and must equal the project-wide overhead total; the invariant is enforced by the bucket-backfill migration (`dwb305c7f1e2a`) and a regression test (`test_overhead_bucket_invariant.py`).

**Per-agent rollup includes overhead** (DWB-306, 2026-06-05). `GET /api/tracking/summary` `per_agent` rows now carry a `tokens` total that aggregates both `token_report` (ticket-attributed) and `overhead_token_report` events, plus a separate `overhead_tokens` field that exposes just the overhead portion. Dashboards see a correct headline number for PM/TL agents while keeping the breakdown visible.

**SubagentStop fallback** (DWB-311, 2026-06-05). Claude Code's SubagentStop hook reports a synthetic `agent_transcript_path` (a `subagents/agent-<sid>.jsonl` file that doesn't exist on disk); the real subagent transcript lives inline in the parent session's `.jsonl` tagged with `agentName`. When the primary parse hits the missing file, `_handle_subagent_stop` walks the CC projects directory and accumulates usage from lines matching the resolved agent's name.

**Large test-result payloads** (DWB-308, 2026-06-05). `test_results.details` is `MEDIUMTEXT` (up to 16MB) so gate-sized payloads — ~600 per-test entries plus a 4000-char output tail, ~85KB — round-trip cleanly. Earlier `TEXT` column capped at 64KB and produced HTTP 500.

**Manual fallback** — Claude Code lifecycle hooks handle backfill and recovery automatically; no separate scan script is needed.

---

## Sprint Gates

Boolean toggles that gate sprint completion:

| Toggle | Check |
|--------|-------|
| `force_test_run` | Test run recorded during sprint |
| `force_test_coverage` | Every router has a test file |
| `force_initial_md` | `INITIAL.md` exists at repo root |
| `force_architecture_md` | `ARCHITECTURE.md` exists at repo root |
| `force_handoff_md` | `HANDOFF.md` exists at repo root |
| Failure records | Unreviewed stubs always block close |

Check gates: `GET /api/projects/{id}/gate-status`

On sprint completion: alerts fire to TL/PM/tester, test ticket auto-created for next sprint.

---

## Failure Analysis

**Auto-detected:** Ticket moves back to `in_progress` after `done` → rework failure record + PM alert. Failed test result → one failure record per failed test.

**Manual taxonomy:** Types A–G for categorization by the PM.

Unreviewed failure stubs block sprint close. Summary: `GET /api/failure-records/summary`.

---

## Alerts

Alerts are flags raised by agents or automation that need human attention. Severities: info (blue), warning (yellow), critical (red).

**Dashboard** — read-only table with columns: Project, Severity, Title, Created. Project links to the project page.

**Project page** — full alert cards with dismiss and action buttons:
- `$ dismiss all` — bulk dismiss open alerts
- `$ send to team` — writes `ALERTS_PENDING.md` to the project repo so teammates can read it

---

## Jira Integration

Projects can optionally link to Jira. One DWB ticket = one Jira issue (1:1 via `jira_issue_key`). Enable/disable via the Tools panel on the project page. Disabling clears all Jira links from project tickets (Jira data is never modified).

- Enable: `PATCH /api/projects/{id}` with `jira_project_key` and `jira_base_url`
- Disable: `POST /api/projects/{id}/disable-jira`

---

## Error Logging

The frontend reports errors to the backend via `POST /api/errors`. The API client automatically captures failed requests (endpoint, status, message, stack trace). View logged errors via `GET /api/errors`.

---

## Testing

```bash
cd backend && pytest tests/                                              # local
./backend/scripts/run_tests.sh --post --project-id 1 --triggered-by "manual"    # with API reporting
```

Or trigger via API: `POST /api/system/run-tests`

Coverage check: `GET /api/status/test-coverage`
Run history: `GET /api/test-results/performance`

---

## Adding a Project

**Demo project:** `POST /api/projects/seed-demo` — creates a fully-populated demo project (prefix `DMO`) with agents, epics, sprints, tickets, test results, and alerts. Idempotent.

**From repo:** `POST /api/projects/from-repo` with `{"repo_path": "/path/to/repo"}` — auto-detects name, prefix, description.

**Then:** assign agents, create epic, create sprint with a goal, deploy playbooks, create tickets.

---

## API Reference

112 endpoints across 19 routers. Full interactive docs at http://localhost:8000/docs.

**Slim responses:** List endpoints strip heavy fields by default — test-results omit `details` (can be 65k+), agents omit `api_key`. Tickets, alerts, and sprints support `?fields=slim` for minimal payloads (id, key fields, status only).

Standard CRUD exists for all resources (projects, epics, sprints, tickets, agents, alerts, comments, instructions, failure records, activity logs, test results). Below are the non-obvious and automation endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects/from-repo` | Create project from repo scan |
| POST | `/api/projects/seed-demo` | Seed demo project (idempotent) |
| POST | `/api/projects/{id}/deploy-playbooks` | Deploy playbooks to project repo |
| POST | `/api/projects/{id}/disable-jira` | Disable Jira, clear all issue links |
| GET | `/api/projects/{id}/gate-status` | Check sprint gates |
| GET | `/api/projects/{id}/activity-feed` | Activity feed (newest first) |
| GET | `/api/projects/{id}/docs` | Scan project doc files |
| GET | `/api/projects/{id}/playbook-files` | List deployed playbook files |
| GET | `/api/projects/{id}/token-budget` | Context file token counts + ceilings |
| POST | `/api/tickets/stale-check` | Stale ticket alert (called by frontend timer) |
| POST | `/api/tracking/start` | Log work start |
| POST | `/api/tracking/stop` | Log work stop |
| POST | `/api/tracking/tokens` | Report tokens |
| POST | `/api/tracking/overhead/start` | Start overhead tracking |
| POST | `/api/tracking/overhead/stop` | Stop overhead tracking |
| GET | `/api/tracking/summary` | Project tracking summary |
| POST | `/api/hooks/session-start` | Receive SessionStart hook |
| POST | `/api/hooks/session-end` | Receive SessionEnd/SubagentStop hook |
| GET | `/api/hooks/sessions` | List hook sessions (filter by `status=orphan` for cleanup) |
| POST | `/api/agents/identify` | Resolve identity from `(role, name, project_prefix)` — accepts short or `<name>_<PREFIX>` form (DWB-289, 315) |
| POST | `/api/agents/spawn-prepare` | Identify + return ready-to-paste markdown for the spawn brief |
| POST | `/api/agents/{id}/session-complete` | Append session entry to scratchpad / lessons / recent_sessions (DWB-293) |
| POST | `/api/agents/{id}/scaffold-memory` | Idempotently scaffold the agent's memory dir |
| GET | `/api/projects/{id}/team` | Single-roundtrip team roster (DWB-313) |
| DELETE | `/api/test-results/{id}` | Operator orphan-row cleanup, 204/404 (DWB-310) |
| POST | `/api/alerts/dismiss-all` | Bulk dismiss open alerts |
| POST | `/api/alerts/send-to-team` | Write alerts to ALERTS_PENDING.md |
| POST | `/api/alerts/run-tests` | Request a test run |
| POST | `/api/errors` | Log frontend error |
| GET | `/api/errors` | List logged errors |
| GET | `/api/tokens/audit` | Token usage audit |
| GET | `/api/failure-records/summary` | Aggregated failure analysis |
| GET | `/api/status` | Health check |
| GET | `/api/status/test-coverage` | Router test coverage |
| POST | `/api/system/run-tests` | Trigger test suite |

---

## Configuration

See `.env.example` for all environment variables. Key settings:

| Variable | Default | Notes |
|----------|---------|-------|
| `MYSQL_PORT` | `23847` | Docker-mapped MySQL port |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Frontend API base |
| `PMA_PORT` | `8080` | phpMyAdmin port |
