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

**Per-project rows, system-wide unique names** (DWB-287, 315). Each agent has one `project_id`; `agents.name` is `UNIQUE` system-wide, so fixed roles recurring across projects take a `_<PREFIX>` suffix (`Archie_DWB`). Identify accepts either form.

**Spawn-time identity flow.** A teammate calls `POST /api/agents/identify` for its `agent_id` and memory dir. Subagent token attribution uses a pending-marker scheme the TL writes at spawn; details in [ARCHITECTURE.md](ARCHITECTURE.md) § 5.

### Team Status

The LiveSessions panel on each project page shows assigned agents with real-time status (active when holding an `in_progress` ticket) and a score leaderboard. Elapsed time ticks from the ticket's `updated_at`.

**Stale detection:** a frontend timer fires `POST /api/tickets/stale-check` when an in_progress ticket crosses a 10-min boundary, raising a deduped alert.

### Deployable Playbooks

Master playbooks in `docs/` (`team_lead_playbook.md`, `pm_playbook.md`, `worker_playbook.md`) deploy to other repos via `POST /api/projects/{id}/deploy-playbooks`; the project page shows `playbooks_deployed_at`.

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

A DWB session is a user-bounded span of work: it opens when you signal start, closes when you signal stop, and rolls up tokens and time across every CC session in between. Single-active per project, DB-enforced. Detection: open/close regex, a SessionEnd transcript retry, `/dwb-open` and `/dwb-close`, and an idle sweeper. Full reference: [docs/session_lifecycle.md](docs/session_lifecycle.md).

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
| `force_coding_standards_md` | `CODING_STANDARDS.md` exists at repo root |
| `force_standards_audit` | A **passing** standards audit recorded in the sprint window (see [Standards Audit](#standards-audit)) |
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

## Standards Audit

A PR/diff is judged against the global standards sheet (`docs/rules/global/coding-standards.md`) plus the repo's own `## Project Extensions` (adds to the sheet, never overrides) by a **fresh, single-purpose auditor** spawned headless with only that law + the diff — no team history, so it cannot rubber-stamp. Verdict, violations, and per-agent scorecard record via `POST /api/standards-audits`.

Run via `scripts/run_standards_audit.sh` (config from `.env`: `STANDARDS_AUDIT_MODEL` etc). Diff selection: `--branch <name>` (vs merge-base), `--range a..b`, or `--staged`; `--dry-run` prints without POSTing.

**Attribution:** `--ticket-id` (author = assignee) or `--author <name>` injects a facts-only names/roles block; the auditor names those agents in the scorecard (worker deltas on the author; TL only on repeat-survival; PM only on a ticketing signal). Unknown returned names **fail loudly before POST**. Malformed auditor output never posts (non-zero exit).

**Applying:** recording does not move scores. `POST /api/standards-audits/{id}/apply-scorecard` is the explicit idempotent second step — deltas to the `score_event` ledger as **The_Auditor**, bypassing peer caps by design.

**Visibility:** every audit raises an alert (info=pass, warning=reject) + activity entry; the Audits page (`/projects/:id/audits`) shows stats and expandable verdict rows. **As a gate:** with `force_standards_audit` ON, sprint close requires a passing audit in-window.

---

## Archie Channel

A cross-project channel for team-leads to message each other, direct (one TL) or broadcast (all). Every TL sees every message; addressing drives the ping only (direct alerts the target, broadcast the other TLs). Unread surfaces atop a TL's `identity.md` on spawn, marked read once shown. Reply via `/tl`. Tables: `tl_messages` + `tl_message_reads` (not project-scoped).

---

## Inter-Agent Comms

Native Claude Code SendMessage traffic is captured per project (DWB-446..449): a `PostToolUse` hook posts each message to `POST /api/hooks/agent-message`, where the sender resolves from the CC `session_id` and the recipient best-effort by name (bodies are stored: agent text). The `/projects/:id/comms` page lists them newest-first with a clear-all. Per-project `capture_agent_comms` (default ON) gates capture; rows older than 4 days are purged. Table: `inter_agent_messages`.

---

## Alerts

Flags raised by agents or automation needing human attention (info/warning/critical). Dashboard shows a read-only table; the project page shows full cards with `$ dismiss all` and `$ send to team` (writes `ALERTS_PENDING.md` into the project repo).

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

API: trigger `POST /api/system/run-tests`, coverage `GET /api/status/test-coverage`, history `GET /api/test-results/performance`.

---

## Adding a Project

**Demo:** `POST /api/projects/seed-demo` creates a fully-populated demo (prefix `DMO`) with agents, epics, sprints, tickets, and test results. Idempotent.

**From repo:** `POST /api/projects/from-repo` with `{"repo_path": "..."}` auto-detects name, prefix, and description.

**Then:** assign agents, create epic + sprint (with a goal), deploy playbooks, tickets.

---

## API Reference

149 endpoints across 25 routers. **The full reference is the interactive docs at http://localhost:8000/docs** (every route, schema, and example); `CLAUDE.md` carries the day-to-day quick table. Standard CRUD exists for all resources.

**Slim responses:** List endpoints strip heavy fields by default (test-results omit `details`, agents omit `api_key`); tickets/alerts/sprints support `?fields=slim`.

The non-obvious and automation endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects/from-repo` | Create project from repo scan |
| POST | `/api/projects/{id}/deploy-playbooks` | Deploy playbooks/skills/hooks to project repo |
| GET | `/api/projects/{id}/gate-status` | Check sprint gates |
| GET | `/api/tracking/summary` | Tracking rollup (tracking ops under `/api/tracking/*`) |
| GET | `/api/projects/{id}/ticket-token-baseline` | Per done-ticket tokens/time + per-sprint count/median/mean/p90; `sprint_id`/`since` filters; zero-token rows counted separately (DWB-539 attribution gap) |
| POST | `/api/hooks/*` | CC lifecycle receivers: session-start/end, tool-use, lifecycle-event, agent-message, post-commit |
| POST | `/api/sessions/open`, `/api/sessions/{id}/close` | DWB session bounds; omit `opened_at` (server-stamped); `headline` required on AI closes; write-on-close gate on explicit closes |
| GET | `/api/sessions/{id}` | DWB session detail rollup (by_role/by_ticket/overhead) |
| POST | `/api/agents/identify`, `/api/agents/spawn-prepare` | Identity resolution; spawn-prepare returns the brief + full `memory_full` for prompt injection |
| POST | `/api/agents/{id}/memory/append`, `.../session-complete` | Memory writes; refuse 400 over the 4500-token ceiling (no silent trim) |
| POST | `/api/agents/{id}/memory/condense` | Sanctioned full-file rewrite to get back under ceiling |
| GET | `/api/projects/{id}/nodes`, `.../nodes/match?text=` | Node index: weighted tags + pointers; match derives neighbors |
| POST | `/api/projects/{id}/nodeify` | Bootstrap/refresh the node index (idempotent renodify) |
| GET/POST | `/api/tl-channel` (+ `/unread`, `/mark-read`) | Cross-project team-lead channel |
| GET/POST | `/api/standards-audits` (+ `/{id}/apply-scorecard`) | Audit verdicts + idempotent scorecard application |
| POST | `/api/projects/{id}/scores/award`, `.../scores/peer` | Human and peer carrot/stick (`X-Agent-ID` on peer) |
| GET | `/api/projects/{id}/team` | Single-roundtrip live roster |
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
