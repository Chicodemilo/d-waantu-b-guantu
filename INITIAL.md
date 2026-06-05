# INITIAL.md — D'Waantu B'Guantu (DWB)

## Why We Built This

Running a team of Claude Code agents — a team lead, PM, frontend dev, backend dev, system ops, and tester — produces a lot of activity that's invisible to the human operator. Tickets move, tokens burn, agents go idle or get stuck, and the only feedback loop is reading terminal output across six split panes. We needed a dashboard that answers two questions at a glance: *what are they doing?* and *how do I change what they're doing?*

DWB was built to solve that. It's a local-first workflow tracker purpose-built for coordinating autonomous AI agents working as a software team.

---

## Original Requirements

Two core functions, stated at the start:

1. **Monitor progress on Claude multi-agent workflows** — see which agents are active, what tickets they're working, how many tokens they've burned, and whether anything is blocked or failing.

2. **Manage team instructions** — give agents rules at three levels (global, per-project, per-agent) and have those rules persist across sessions, sync with Claude memory files, and be editable from the dashboard.

These requirements came from running real multi-agent builds where the team lead orchestrates through Claude Code's Teams feature, and the human operator needs visibility without interrupting the agents.

---

## Project Phases

**Phase 0 — Architecture & Data Model.** Hierarchy (Project → Epic → Sprint → Ticket), agent model, instruction scoping (global/project/agent), alert system. Read-heavy dashboard, PM is primary writer, no ticket priority levels, terminal UI.

**Phase 1 — Multi-Agent Build.** Built via Claude Code subagents in waves, then switched to Claude Code Teams (persistent teammates, TL orchestrates via instructions).

**Phase 2 — Iteration & Automation.** Token tracking hooks, sprint gates, auto-assignment defaults, sprint lifecycle alerts, instruction sync, playbook deployment, token audit.

**Phase 3 — Product Maturity.** Failure analysis, test performance tracking, forced project docs, comprehensive usage docs, rules moved into repo files (in progress).

---

## Key Design Decisions

### Read-heavy dashboard, PM writes

The human operator reads the dashboard. The PM agent observes other agents and writes updates — creating tickets, posting comments, updating statuses. Working agents focus on work; the PM hovers and records. This separation means the UI doesn't need complex forms for the human — it needs clear, dense data display.

### Token tracking as first-class concern

Every ticket tracks `tokens_used` and `time_spent_seconds`. Team lead and PM tokens are tracked separately as project "overhead" since their work spans across tickets. A stop hook automatically reports tokens from Claude Code session transcripts — agents don't have to remember to self-report, though they can via `POST /api/tickets/:id/tokens`.

When a ticket is closed with zero tokens, an alert fires. This was a deliberate enforcement choice — if an agent did work, the tokens should be recorded.

### Terminal UI aesthetic

Black background (#000000), pale green (#4ade80), orange (#fb923c), light blue (#93c5fd), JetBrains Mono font. Inspired by htop and terminal dashboards. ASCII progress bars and charts on the dashboard page. The aesthetic matches the environment — these agents live in terminals, so the dashboard should feel like one.

### Plain CSS, no frameworks

Vanilla CSS with CSS custom properties, organized by component area (theme.css, layout.css, tickets.css, charts.css). No Tailwind, no CSS-in-JS. The terminal aesthetic is simple enough that a framework adds complexity without value. CSS stays in files, not inline `style={}` props.

### Adaptive polling, not WebSockets

The frontend polls the API at 2-second intervals when agents are active, 10 seconds when idle. Status endpoint drives the interval decision. WebSockets would add infrastructure complexity for a local-first single-user app. Polling is simple, debuggable, and sufficient.

### Zustand for state

Lightweight state management with per-resource slices. No Redux ceremony. Each resource (projects, tickets, agents, etc.) has its own hook and store slice, refreshed by the polling loop.

### Three-layer backend

FastAPI routers handle HTTP. Services contain business logic. Models define the schema. Schemas (Pydantic) define request/response shapes. This separation keeps routers thin and makes the service layer testable.

### Auto-assignment defaults

Creating a ticket without specifying `sprint_id` finds the project's active sprint. Creating a sprint without `epic_id` finds the project's latest open epic. Tickets inherit `epic_id` from their sprint. This keeps the API ergonomic for agents who shouldn't need to track the full hierarchy.

---

## Constraints

### Local-first, single user

Runs entirely on an M4 Mac. MySQL in Docker, backend and frontend on localhost. No deployment target, no multi-tenancy, no auth beyond an API key. This is an operator's tool, not a SaaS product.

### One project at a time (initially)

The system supports multiple projects (DWB, INGEST, RECON, DOCS) but the workflow assumption is that one project gets active attention at a time. The dashboard shows all projects, but sprint gates and token tracking are designed for focused single-project sprints.

### Agents are Claude Code teammates

Agents in the database map 1:1 to Claude Code teammates. The `role` field matches the teammate name (e.g., `backend-worker`, `team-lead`). Agent names are human names (Archie, Devin, Pixel) because the PM refers to them by name in comments and alerts. The stop hook matches agents by role or name against the API.

### No persistent processes beyond Docker

The backend runs via `uvicorn` in a terminal. The frontend runs via `vite dev`. There's no process manager, no systemd, no PM2. If the terminal closes, the server stops. This is intentional — the operator controls everything.

---

## Success Criteria

1. **Visibility** — at any moment, the operator can see which agents are working, what they're working on, how many tokens they've used, and whether anything is blocked.

2. **Instruction control** — the operator can add, modify, or remove rules at global, project, or agent scope, and those rules persist across Claude Code sessions.

3. **Token accountability** — every token spent on a project is accounted for, either at the ticket level or as overhead. Discrepancies are flagged.

4. **Sprint discipline** — sprints have enforceable gates (tests run, coverage met, docs written) that prevent premature closure.

5. **Minimal operator overhead** — the dashboard requires no data entry from the human. The PM agent does the writing. The operator reads and gives high-level direction through Claude Code.

6. **Self-documenting** — the system tracks its own development (DWB is project 1 in its own database), making it a live example of what it manages.
