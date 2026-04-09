# Local Agent Tracker — Implementation Plan

## Context
Build a local dashboard for monitoring Claude multi-agent workflows. The app is **read-heavy** — the human user consumes info, a PM agent writes updates. The user manages agents via Claude Code; the dashboard is for visibility, not editing.

---

## Tech Stack
| Layer | Choice |
|-------|--------|
| Frontend | React JSX + Vite + Zustand |
| CSS | Plain CSS files with CSS custom properties for theming. No framework. |
| Backend | Python + FastAPI |
| DB | MySQL 8 (Docker) + Alembic migrations |
| DB Admin | phpMyAdmin (Docker) |
| Config | `.env` + `pydantic-settings` |
| Theme | Terminal: black bg, pale green text, orange accent, light blue secondary, monospace (JetBrains Mono) |

---

## Multi-Agent Build Strategy

Using Claude Code multi-agent mode with 4 sub-agents:

### Agent Roles
1. **DBA Bot** — docker-compose, .env, Alembic setup, SQLAlchemy models, initial migration
2. **API Bot** — FastAPI app, config, auth, all routers/schemas/services
3. **React Bot** — Vite setup, components, pages, CSS (plain CSS + custom properties), routing
4. **Data Bot** — api/client.js, all frontend API modules, hooks, wires real data into React components

### Build Waves (dependency order)
- **Wave 1** (parallel): DBA Bot + React Bot (CSS/components with placeholder data)
- **Wave 2** (depends on Wave 1): API Bot (needs DBA's models)
- **Wave 3** (depends on Wave 2): Data Bot (needs API endpoints + React components)

---

## Database Schema (10 tables)

1. **projects** — id, prefix (unique, e.g. "LAT"), name, description, status, tl_overhead_tokens, pm_overhead_tokens, tl_overhead_time_seconds, pm_overhead_time_seconds, timestamps
2. **sprints** — id, project_id FK, name, goal, sprint_number, status (planned/active/completed), start_date, end_date, timestamps
3. **epics** — id, project_id FK, name, description, status, timestamps
4. **agents** — id, name, description (text), role (team_lead/pm/developer/reviewer/specialist), api_key (unique), is_active, timestamps
5. **project_agents** — id, project_id FK, agent_id FK (unique combo), assigned_at
6. **tickets** — id, project_id FK, epic_id FK (nullable), sprint_id FK (nullable), assigned_agent_id FK (nullable), ticket_number, ticket_key (e.g. "LAT-001"), title, description, ticket_type (task/bug/story), status (backlog/todo/in_progress/in_review/done), tokens_used, time_spent_seconds, timestamps, completed_at
7. **comments** — id, ticket_id FK, author_agent_id FK, body, created_at
8. **alerts** — id, project_id FK, raised_by_agent_id FK, ticket_id FK (nullable), title, body, severity (info/warning/critical), status (open/acknowledged/resolved), created_at, resolved_at
9. **instructions** — id, scope (global/project/agent), project_id FK (nullable), agent_id FK (nullable), title, body (markdown), timestamps
10. **activity_log** — id, project_id FK, agent_id FK (nullable), entity_type, entity_id, action, details (JSON), created_at

### Token Tracking Strategy
- Per-ticket: stored directly, updated via additive deltas (not replace)
- Per-sprint: computed at query time `SUM(tickets.tokens_used) WHERE sprint_id = ?`
- Per-project: computed = all ticket tokens + tl_overhead_tokens + pm_overhead_tokens
- TL/PM overhead: separate running tallies on the project row (don't roll up from tickets)

---

## Directory Structure

```
d-waantu_b-guantu/
├── docker-compose.yml
├── .env / .env.example / .gitignore
├── PLAN.md
├── backend/
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/001_initial_schema.py
│   └── app/
│       ├── main.py              # FastAPI app, CORS, routers
│       ├── config.py            # pydantic-settings from .env
│       ├── database.py          # SQLAlchemy engine + session
│       ├── auth.py              # API key auth + project scoping
│       ├── models/              # 10 SQLAlchemy models
│       ├── schemas/             # Pydantic request/response models
│       ├── routers/             # dashboard, projects, sprints, epics, tickets, agents, comments, alerts, instructions, activity
│       └── services/            # ticket_service, token_service, activity_service
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx / App.jsx
│       ├── styles/              # theme.css (vars + base), layout.css, tickets.css, charts.css, etc.
│       ├── api/                 # client.js + per-entity modules
│       ├── hooks/               # usePolling, useProjects, useTickets, useDashboard
│       ├── components/
│       │   ├── layout/          # AppShell, Sidebar, Header, Footer
│       │   ├── common/          # StatusBadge, DataTable, AsciiChart, AsciiProgressBar, ActivityFeed, AlertBanner
│       │   ├── dashboard/       # ProjectCard, CrossProjectSummary, TokenOverview
│       │   ├── project/         # ProjectHeader, SprintProgress, OverheadTracker
│       │   ├── tickets/         # TicketList, TicketDetail, TicketFilters, TicketComments
│       │   ├── agents/          # AgentList, AgentDetail, AgentMetrics
│       │   ├── sprints/         # SprintDetail, SprintVelocity
│       │   ├── epics/           # EpicList, EpicDetail
│       │   └── instructions/    # InstructionList, InstructionView
│       └── pages/               # DashboardPage, ProjectPage, TicketsPage, AgentPage, SprintPage, EpicPage, InstructionsPage
```

---

## API Endpoints

**Auth**: All endpoints require `X-API-Key` header. Admin key (from .env) = full access. Agent keys = scoped to assigned projects.

### Dashboard (admin key only)
- `GET /api/dashboard` — cross-project summary
- `GET /api/dashboard/tokens` — token breakdown across all projects
- `GET /api/dashboard/activity` — recent activity across all projects

### Projects
- `GET/POST /api/projects`
- `GET/PATCH /api/projects/{id}`

### Sprints (project-scoped)
- `GET/POST /api/projects/{id}/sprints`
- `GET/PATCH /api/projects/{id}/sprints/{sprint_id}`

### Epics (project-scoped)
- `GET/POST /api/projects/{id}/epics`
- `GET/PATCH /api/projects/{id}/epics/{epic_id}`

### Tickets (project-scoped)
- `GET/POST /api/projects/{id}/tickets` — list supports filters: status, type, sprint_id, epic_id, agent_id, sort, order
- `GET/PATCH /api/projects/{id}/tickets/{ticket_id}`
- `PATCH /api/projects/{id}/tickets/{ticket_id}/status` — dedicated status transition
- `PATCH /api/projects/{id}/tickets/{ticket_id}/tokens` — additive token/time delta

### Comments (ticket-scoped)
- `GET/POST /api/projects/{id}/tickets/{ticket_id}/comments`

### Agents
- `GET/POST /api/agents`
- `GET/PATCH /api/agents/{id}`
- `POST/DELETE /api/agents/{id}/projects/{project_id}` — assign/unassign
- `GET /api/agents/{id}/tickets` — all tickets for this agent

### Alerts (project-scoped)
- `GET /api/alerts` — all open alerts (admin/dashboard)
- `GET/POST /api/projects/{id}/alerts`
- `PATCH /api/projects/{id}/alerts/{alert_id}`

### Instructions
- `GET/POST /api/instructions` — filters: scope, project_id, agent_id
- `GET/PATCH /api/instructions/{id}`

### Activity Log
- `GET /api/projects/{id}/activity` — filters: limit, offset, entity_type

---

## UI Design

### Terminal Theme (Plain CSS + custom properties)
```css
:root {
  --bg: #000000;
  --bg-alt: #0a0a0a;
  --bg-hover: #111111;
  --green: #4ade80;
  --green-dim: #22c55e;
  --green-bright: #86efac;
  --orange: #fb923c;
  --orange-bright: #fdba74;
  --blue: #93c5fd;
  --blue-dim: #60a5fa;
  --gray: #525252;
  --gray-light: #737373;
  --border: #262626;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
}
```

### ASCII Charts (custom, no library)
- Horizontal bars: `████████████░░░░░░░░` with labels, percentages
- Progress bars: `[████████░░░░] 67%`
- Sparklines: `▁▂▃▅▇█▇▅▃` (Unicode block chars)

### Routing
- `/` — Dashboard (all projects, ASCII token charts, alerts summary)
- `/projects/:id` — Project overview (overhead tally, sprint progress, activity feed, alerts)
- `/projects/:id/tickets` — Sortable/filterable ticket list
- `/projects/:id/tickets/:ticketId` — Ticket detail + comments
- `/projects/:id/sprints/:sprintId` — Sprint detail + velocity
- `/projects/:id/epics/:epicId` — Epic detail
- `/agents/:id` — Agent view with metrics + tickets
- `/instructions` — Global/project/agent instructions (read-only display)

### Data Freshness — Adaptive Polling + Zustand
- **Zustand store** manages all server state (agents, tickets, projects, alerts, dashboard)
- **Adaptive polling** via `usePolling` hook — adjusts interval based on activity:
  - ~2s when agents are actively working (active tickets in progress)
  - ~10s when idle (no in-progress work)
- Poll hits status endpoint, Zustand store updates, components re-render reactively
- No websockets — overkill for single-user local app

---

## .env Template

```bash
# Database
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=local_agent_tracker
MYSQL_USER=lat_user
MYSQL_PASSWORD=lat_dev_password
MYSQL_ROOT_PASSWORD=lat_root_password

# API
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=true
ADMIN_API_KEY=lat-admin-CHANGE-ME-TO-RANDOM-64-CHAR-HEX

# Frontend
VITE_API_BASE_URL=http://localhost:8000/api
VITE_POLL_INTERVAL_MS=10000

# phpMyAdmin
PMA_PORT=8080
```

---

## Key Decisions Log

- Dashboard is READ-HEAVY — user consumes, PM agent writes
- PM agent creates/updates all board data (projects, sprints, tickets, comments)
- Working agents focus on code, not board updates
- User gives instructions via Claude Code to Team Lead, not via the dashboard
- No priority levels — ticket exists or doesn't (backlog or delete)
- Ticket types: Task, Bug, Story
- Statuses: Backlog → To Do → In Progress → In Review → Done
- Token tracking: additive deltas per ticket, computed rollups for sprints/projects
- TL/PM overhead tokens tracked separately on project row
- Sprints laid out at project start, adjusted via Claude Code → PM updates board
- Alerts: PM can flag questions for user, user answers in Claude Code
- One project at a time to start
- No CSS framework — plain CSS with custom properties
- API auth: per-agent API keys scoped to assigned projects, admin key for dashboard

---

## Verification

1. `docker compose up -d` — MySQL and phpMyAdmin running at localhost:8080
2. `alembic upgrade head` — all 10 tables created (verify in phpMyAdmin)
3. `uvicorn app.main:app --reload` — API at localhost:8000, Swagger docs at /docs
4. Create agent via POST /api/agents → returns API key
5. Create project, assign agent, create sprint/epic/tickets via API
6. `npm run dev` — frontend at localhost:5173, terminal theme renders
7. Dashboard shows project with ASCII charts
8. Navigate to project → see tickets, activity feed
9. Ticket detail shows comments
10. Agent view shows assigned tickets and token metrics
