# Path: app/services/seed_demo.py
# File: seed_demo.py
# Created: 2026-03-30
# Purpose: Seeds a full demo project (prefix=DMO) with plausible data for dashboard showcase
# Caller: app/routers/projects.py (POST /api/projects/seed-demo)
# Callees: All ORM models, app/services/project.delete_project
# Data In: db: Session
# Data Out: dict with created entity counts
# Last Modified: 2026-03-30

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.epic import Epic, EpicStatus
from app.models.failure_record import FailureRecord
from app.models.project import Project, ProjectStatus
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.test_result import TestResult, TestStatus
from app.models.ticket import Ticket, TicketStatus, TicketType
from app.services.project import delete_project

# ---------------------------------------------------------------------------
# Demo data definitions
# ---------------------------------------------------------------------------

DEMO_PREFIX = "DMO"
DEMO_PROJECT_NAME = "Demo Corp Portal"
DEMO_PROJECT_DESC = (
    "DEMO DATA — Not a real project. Fake full-stack customer portal with auth, "
    "analytics, and API integrations. Seeded to showcase the DWB tracking system."
)

AGENTS = [
    {"name": "Archie",  "role": "team-lead",       "description": "Team lead — orchestrator",       "api_key": "dmo-key-tl"},
    {"name": "Pam",     "role": "pm",              "description": "Project manager — ticket ops",   "api_key": "dmo-key-pm"},
    {"name": "Freddie", "role": "frontend-worker",  "description": "React / Vite frontend dev",     "api_key": "dmo-key-fe"},
    {"name": "Barry",   "role": "backend-worker",   "description": "FastAPI backend dev",           "api_key": "dmo-key-be"},
    {"name": "Chester", "role": "tester",           "description": "Test runner and QA",            "api_key": "dmo-key-qa"},
]

EPICS = [
    {"name": "User Authentication",    "description": "Login, registration, password reset, session management", "status": EpicStatus.completed},
    {"name": "Dashboard Analytics",    "description": "Charts, KPIs, real-time metrics, export to CSV",          "status": EpicStatus.in_progress},
    {"name": "API Integration Layer",  "description": "Third-party webhook ingestion, outbound REST calls",      "status": EpicStatus.open},
]

# (epic_index, sprint_number, name, goal, status, start_offset_days, duration_days)
SPRINTS = [
    (0, 1, "Auth Scaffold",         "Basic login/register flow",                   SprintStatus.completed, -28, 7),
    (0, 2, "Session & Tokens",      "JWT refresh, cookie security, logout",        SprintStatus.completed, -21, 7),
    (1, 3, "Chart Components",      "Recharts integration, 4 chart types",         SprintStatus.completed, -14, 7),
    (1, 4, "KPI Cards & Filters",   "Server-side filtering, KPI summary cards",    SprintStatus.completed, -7,  7),
    (1, 5, "Real-time Metrics",     "WebSocket push, live dashboard refresh",      SprintStatus.active,    0,   7),
    (2, 6, "Webhook Receiver",      "Inbound webhook endpoint + signature verify", SprintStatus.planned,   7,   7),
]

# (sprint_index, ticket_number, title, type, status, assigned_agent_index, tokens, time_seconds)
TICKETS = [
    # Sprint 1 — Auth Scaffold (all done)
    (0, 1,  "Create users table migration",         TicketType.task,  TicketStatus.done,        3, 2400,   900),
    (0, 2,  "Build registration endpoint",           TicketType.task,  TicketStatus.done,        3, 8700,  2700),
    (0, 3,  "Build login endpoint with JWT",         TicketType.task,  TicketStatus.done,        3, 6300,  1800),
    (0, 4,  "Create login page UI",                  TicketType.task,  TicketStatus.done,        2, 5100,  1500),
    (0, 5,  "Create registration page UI",           TicketType.task,  TicketStatus.done,        2, 4200,  1200),
    # Sprint 2 — Session & Tokens (all done)
    (1, 6,  "Implement JWT refresh token rotation",  TicketType.task,  TicketStatus.done,        3, 11200, 3600),
    (1, 7,  "Add httpOnly cookie support",           TicketType.task,  TicketStatus.done,        3, 3900,  1200),
    (1, 8,  "Build logout endpoint",                 TicketType.task,  TicketStatus.done,        3, 1800,   600),
    (1, 9,  "Fix token expiry off-by-one",           TicketType.bug,   TicketStatus.done,        3, 4500,  1500),
    (1, 10, "Add auth guard to protected routes",    TicketType.task,  TicketStatus.done,        2, 3200,  1050),
    # Sprint 3 — Chart Components (all done)
    (2, 11, "Install and configure Recharts",        TicketType.task,  TicketStatus.done,        2, 1500,   450),
    (2, 12, "Build line chart component",            TicketType.task,  TicketStatus.done,        2, 7800,  2400),
    (2, 13, "Build bar chart component",             TicketType.task,  TicketStatus.done,        2, 6200,  1800),
    (2, 14, "Build pie chart component",             TicketType.task,  TicketStatus.done,        2, 5900,  1650),
    (2, 15, "Build area chart component",            TicketType.task,  TicketStatus.done,        2, 5400,  1500),
    (2, 16, "Write chart component tests",           TicketType.task,  TicketStatus.done,        4, 8200,  2700),
    # Sprint 4 — KPI Cards & Filters (all done)
    (3, 17, "Design KPI card component",             TicketType.story, TicketStatus.done,        2, 4100,  1200),
    (3, 18, "Build server-side date range filter",   TicketType.task,  TicketStatus.done,        3, 9400,  3000),
    (3, 19, "Build category filter dropdown",        TicketType.task,  TicketStatus.done,        2, 3600,  1050),
    (3, 20, "Connect filters to chart data",         TicketType.task,  TicketStatus.done,        2, 7100,  2100),
    (3, 21, "Fix filter reset not clearing charts",  TicketType.bug,   TicketStatus.done,        2, 2800,   900),
    # Sprint 5 — Real-time Metrics (active, mixed statuses)
    (4, 22, "Set up WebSocket endpoint",             TicketType.task,  TicketStatus.done,        3, 6800,  2100),
    (4, 23, "Build live chart update hook",          TicketType.task,  TicketStatus.in_review,   2, 5200,  1650),
    (4, 24, "Add connection status indicator",       TicketType.task,  TicketStatus.in_progress, 2, 1200,   450),
    (4, 25, "Handle WebSocket reconnection",         TicketType.task,  TicketStatus.todo,        3, 0,       0),
    (4, 26, "Write WebSocket integration tests",     TicketType.task,  TicketStatus.todo,        4, 0,       0),
    # Sprint 6 — Webhook Receiver (planned)
    (5, 27, "Design webhook payload schema",         TicketType.story, TicketStatus.backlog,     3, 0,       0),
    (5, 28, "Build webhook receiver endpoint",       TicketType.task,  TicketStatus.backlog,     3, 0,       0),
    (5, 29, "Implement HMAC signature verification", TicketType.task,  TicketStatus.backlog,     3, 0,       0),
    (5, 30, "Add webhook event log table",           TicketType.task,  TicketStatus.backlog,     3, 0,       0),
]

# (sprint_index, suite, total, passed, failed, skipped, duration, status, triggered_by)
TEST_RESULTS = [
    (0, "backend",  12, 12, 0, 0, 4.2,  TestStatus.passed, "tester"),
    (1, "backend",  18, 17, 1, 0, 6.1,  TestStatus.failed, "tester"),
    (1, "backend",  18, 18, 0, 0, 5.8,  TestStatus.passed, "tester"),
    (2, "frontend", 24, 24, 0, 1, 8.3,  TestStatus.passed, "tester"),
    (3, "backend",  22, 22, 0, 0, 7.1,  TestStatus.passed, "tester"),
    (3, "frontend", 30, 29, 1, 0, 9.7,  TestStatus.failed, "tester"),
    (3, "frontend", 30, 30, 0, 0, 9.2,  TestStatus.passed, "tester"),
    (4, "backend",  26, 25, 1, 0, 8.9,  TestStatus.failed, "tester"),
]

# (ticket_index, failure_type, severity, notes, resolved)
FAILURE_RECORDS = [
    (8,  "integration_failure", "high",   "JWT expiry calculation used seconds instead of milliseconds — caught in staging", True),
    (20, "spec_drift",          "medium", "Filter reset endpoint changed shape after chart refactor, frontend not updated",  True),
]

# (title, body, severity, status, ticket_index_or_none)
ALERTS = [
    ("Sprint 2 test failure — JWT tests",     "1 backend test failed in Sprint 2: test_refresh_token_expired. Resolved after bug fix in DMO-009.", AlertSeverity.warning,  AlertStatus.resolved, 8),
    ("Sprint 4 test failure — filter tests",   "1 frontend test failed: FilterDropdown.test.tsx assertion error on reset. Fixed in DMO-021.",       AlertSeverity.warning,  AlertStatus.resolved, 20),
    ("Sprint 5 test failure — WS endpoint",    "1 backend test failed: test_websocket_broadcast timeout. Investigation in progress.",               AlertSeverity.warning,  AlertStatus.open,     None),
    ("High token usage on DMO-011",            "Recharts install ticket used 1500 tokens for a simple npm install — review scope.",                  AlertSeverity.info,     AlertStatus.acknowledged, None),
]


DEMO_REPO_DIR = Path("/tmp/dwb-demo-project")

_README_MD = """\
# Demo Corp Portal

Full-stack customer portal with authentication, analytics dashboards, and
third-party API integrations.

## Quick Start

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

## Stack

| Layer     | Tech                        |
|-----------|-----------------------------|
| Frontend  | React 18, Vite, Recharts    |
| Backend   | FastAPI, SQLAlchemy 2.0     |
| Database  | PostgreSQL 15               |
| Auth      | JWT (access + refresh)      |
| Real-time | WebSockets                  |

## Project Structure

```
demo-corp-portal/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── services/
│   ├── alembic/
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── pages/
│   │   └── utils/
│   └── tests/
└── docker-compose.yml
```

## Environments

| Env     | URL                         |
|---------|-----------------------------|
| Local   | http://localhost:5173       |
| Staging | https://staging.democorp.io |

## License

Proprietary — Demo Corp Inc.
"""

_INITIAL_MD = """\
# Demo Corp Portal — Project Plan

## Overview

Build a customer-facing portal that consolidates authentication, analytics,
and third-party integrations into a single responsive web application.

## Goals

1. **Secure authentication** — JWT-based login with refresh token rotation,
   httpOnly cookies, and CSRF protection.
2. **Analytics dashboard** — Interactive charts (line, bar, pie, area) with
   server-side filtering and real-time WebSocket updates.
3. **API integration layer** — Inbound webhook receiver with HMAC signature
   verification and outbound REST client with retry logic.

## Milestones

| #  | Milestone               | Target     | Status      |
|----|-------------------------|------------|-------------|
| 1  | Auth scaffold           | Week 1     | Done        |
| 2  | Session & token mgmt    | Week 2     | Done        |
| 3  | Chart components        | Week 3     | Done        |
| 4  | KPI cards & filters     | Week 4     | Done        |
| 5  | Real-time metrics       | Week 5     | In Progress |
| 6  | Webhook receiver        | Week 6     | Planned     |

## Team

| Role             | Agent   |
|------------------|---------|
| Team Lead        | Archie  |
| Project Manager  | Pam     |
| Frontend Dev     | Freddie |
| Backend Dev      | Barry   |
| QA / Tester      | Chester |

## Risks

- WebSocket scaling under high connection count (mitigate with connection pooling)
- Third-party webhook payload schema changes (mitigate with versioned handlers)
- JWT secret rotation during active sessions (mitigate with grace period logic)

## Success Criteria

- All 6 milestones delivered within 6 weeks
- Test coverage above 80% for backend, 70% for frontend
- Zero critical security findings in auth flow
- Dashboard loads in under 2 seconds on 3G connection
"""

_ARCHITECTURE_MD = """\
# Demo Corp Portal — Architecture

## System Overview

```
┌────────────┐     ┌──────────────┐     ┌──────────────┐
│   Browser   │────▶│  Vite/React  │────▶│   FastAPI     │
│  (Client)   │◀────│  Frontend    │◀────│   Backend     │
└────────────┘     └──────────────┘     └──────┬───────┘
                                               │
                          ┌────────────────────┤
                          ▼                    ▼
                   ┌──────────────┐     ┌──────────────┐
                   │  PostgreSQL   │     │  Redis        │
                   │  (Primary DB) │     │  (Sessions)   │
                   └──────────────┘     └──────────────┘
```

## Backend Architecture

### Layer Pattern: Router → Service → Model

```
HTTP Request
  → Router (validation, auth guards, HTTP concerns)
    → Service (business logic, cross-entity orchestration)
      → Model (ORM, DB queries)
        → PostgreSQL
```

### Authentication Flow

1. `POST /auth/register` — create user, hash password (bcrypt)
2. `POST /auth/login` — verify credentials, issue access + refresh JWTs
3. Access token: 15-minute expiry, sent in Authorization header
4. Refresh token: 7-day expiry, httpOnly cookie, rotated on use
5. `POST /auth/refresh` — validate refresh token, issue new pair
6. `POST /auth/logout` — revoke refresh token family

### WebSocket Architecture

- Endpoint: `ws://localhost:8000/ws/metrics`
- Server pushes metric updates every 5 seconds
- Client reconnects with exponential backoff (1s, 2s, 4s, max 30s)
- Connection status shown in dashboard header

## Frontend Architecture

### State Management

- **Server state**: React Query for API data (auto-refetch, caching)
- **UI state**: React useState/useReducer (local component state)
- **No global store** — React Query covers 90% of needs

### Component Hierarchy

```
App
├── AuthProvider (JWT context)
├── Layout
│   ├── Header (nav, user menu, WS status)
│   └── Sidebar (navigation links)
├── Pages
│   ├── LoginPage
│   ├── RegisterPage
│   ├── DashboardPage
│   │   ├── KPICards
│   │   ├── FilterBar (date range, category)
│   │   ├── LineChart
│   │   ├── BarChart
│   │   ├── PieChart
│   │   └── AreaChart
│   └── SettingsPage
└── WebSocketProvider (live metrics context)
```

### Chart Components

All chart components use Recharts with a shared theme configuration.
Each chart accepts a `data` prop and optional `filters` prop.
Responsive containers handle viewport scaling.

## Database Schema (key tables)

```sql
users           (id, email, password_hash, created_at)
refresh_tokens  (id, user_id, token_hash, family_id, revoked, expires_at)
metrics         (id, category, value, recorded_at)
webhook_events  (id, source, payload, signature, verified, received_at)
```

## API Endpoints

| Method | Path                  | Description                 |
|--------|-----------------------|-----------------------------|
| POST   | /auth/register        | Create new user             |
| POST   | /auth/login           | Authenticate, get tokens    |
| POST   | /auth/refresh         | Rotate refresh token        |
| POST   | /auth/logout          | Revoke token family         |
| GET    | /metrics              | List metrics (filterable)   |
| GET    | /metrics/summary      | KPI aggregates              |
| WS     | /ws/metrics           | Real-time metric stream     |
| POST   | /webhooks/inbound     | Receive external webhook    |

## Deployment

- **Docker Compose** for local development (frontend, backend, postgres, redis)
- **Staging**: AWS ECS Fargate, RDS PostgreSQL, ElastiCache Redis
- **CI/CD**: GitHub Actions → build → test → deploy to staging on merge to main
"""


def _create_demo_repo(repo_dir: Path) -> None:
    """Create (or recreate) a fake repo directory with demo doc files."""
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    (repo_dir / "README.md").write_text(_README_MD, encoding="utf-8")
    (repo_dir / "INITIAL.md").write_text(_INITIAL_MD, encoding="utf-8")
    (repo_dir / "ARCHITECTURE.md").write_text(_ARCHITECTURE_MD, encoding="utf-8")
    (repo_dir / "TEAM.md").write_text("# Team — Demo Project\n\nDemo team roster.\n", encoding="utf-8")


def seed_demo_project(db: Session) -> dict:
    """Seed (or re-seed) the demo project with plausible data.

    Idempotent: if a project with prefix=DMO exists, it is fully deleted first.
    Returns a summary dict of created entity counts.
    """
    today = date.today()

    # ── Idempotent cleanup ──────────────────────────────────────────────
    existing = db.scalar(select(Project).where(Project.prefix == DEMO_PREFIX))
    if existing:
        # Also clean up demo agents (they are separate from project cascade)
        demo_agent_keys = [a["api_key"] for a in AGENTS]
        delete_project(db, existing)
        # Delete demo agents that aren't assigned to other projects
        for key in demo_agent_keys:
            agent = db.scalar(select(Agent).where(Agent.api_key == key))
            if agent:
                # Check if assigned to another project
                other = db.scalar(
                    select(ProjectAgent.id)
                    .where(ProjectAgent.agent_id == agent.id)
                )
                if not other:
                    db.delete(agent)
        db.commit()

    # ── Demo repo with doc files ──────────────────────────────────────
    _create_demo_repo(DEMO_REPO_DIR)

    # ── Project ─────────────────────────────────────────────────────────
    project = Project(
        prefix=DEMO_PREFIX,
        name=DEMO_PROJECT_NAME,
        description=DEMO_PROJECT_DESC,
        status=ProjectStatus.active,
        repo_path=str(DEMO_REPO_DIR),
        force_test_run=True,
        force_test_coverage=False,
        force_initial_md=True,
        force_architecture_md=True,
    )
    db.add(project)
    db.flush()

    # ── Agents ──────────────────────────────────────────────────────────
    agent_objs = []
    for a in AGENTS:
        # Re-use existing agent if api_key matches (unlikely after cleanup, but safe)
        agent = db.scalar(select(Agent).where(Agent.api_key == a["api_key"]))
        if not agent:
            agent = Agent(**a)
            db.add(agent)
            db.flush()
        agent_objs.append(agent)
        db.add(ProjectAgent(project_id=project.id, agent_id=agent.id))

    db.flush()

    # ── Epics ───────────────────────────────────────────────────────────
    epic_objs = []
    for e in EPICS:
        epic = Epic(project_id=project.id, **e)
        db.add(epic)
        db.flush()
        epic_objs.append(epic)

    # ── Sprints ─────────────────────────────────────────────────────────
    sprint_objs = []
    for epic_idx, sprint_number, name, goal, status, start_offset, duration in SPRINTS:
        start = today + timedelta(days=start_offset)
        end = start + timedelta(days=duration)
        sprint = Sprint(
            project_id=project.id,
            epic_id=epic_objs[epic_idx].id,
            name=name,
            goal=goal,
            sprint_number=sprint_number,
            status=status,
            start_date=start,
            end_date=end if status == SprintStatus.completed else None,
        )
        db.add(sprint)
        db.flush()
        sprint_objs.append(sprint)

    # ── Tickets ─────────────────────────────────────────────────────────
    ticket_objs = []
    for sprint_idx, tnum, title, ttype, tstatus, agent_idx, tokens, time_s in TICKETS:
        sprint = sprint_objs[sprint_idx]
        completed_at = None
        if tstatus == TicketStatus.done:
            completed_at = datetime.combine(
                sprint.start_date + timedelta(days=3), datetime.min.time()
            )
        ticket = Ticket(
            project_id=project.id,
            epic_id=sprint.epic_id,
            sprint_id=sprint.id,
            assigned_agent_id=agent_objs[agent_idx].id,
            ticket_number=tnum,
            ticket_key=f"DMO-{tnum:03d}",
            title=title,
            ticket_type=ttype,
            status=tstatus,
            tokens_used=tokens,
            time_spent_seconds=time_s,
            token_source="demo_seed" if tokens > 0 else "unknown",
            completed_at=completed_at,
        )
        db.add(ticket)
        db.flush()
        ticket_objs.append(ticket)

    # ── Test Results ────────────────────────────────────────────────────
    for sprint_idx, suite, total, passed, failed, skipped, duration, status, triggered_by in TEST_RESULTS:
        sprint = sprint_objs[sprint_idx]
        run_at = datetime.combine(
            sprint.start_date + timedelta(days=5), datetime.min.time()
        )
        db.add(TestResult(
            project_id=project.id,
            sprint_id=sprint.id,
            suite=suite,
            total_tests=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=duration,
            status=status,
            triggered_by=triggered_by,
            run_at=run_at,
        ))

    # ── Failure Records ─────────────────────────────────────────────────
    pm_agent = agent_objs[1]  # Patty (PM)
    for ticket_idx, ftype, severity, notes, resolved in FAILURE_RECORDS:
        ticket = ticket_objs[ticket_idx]
        db.add(FailureRecord(
            project_id=project.id,
            ticket_id=ticket.id,
            sprint_id=ticket.sprint_id,
            agent_id=ticket.assigned_agent_id,
            logged_by_agent_id=pm_agent.id,
            failure_type=ftype,
            severity=severity,
            notes=notes,
            root_cause=notes,
            resolution="Fixed and re-verified" if resolved else None,
            resolved=resolved,
        ))

    # ── Alerts ──────────────────────────────────────────────────────────
    for title, body, severity, astatus, ticket_idx in ALERTS:
        ticket_id = ticket_objs[ticket_idx].id if ticket_idx is not None else None
        db.add(Alert(
            project_id=project.id,
            raised_by_agent_id=pm_agent.id,
            ticket_id=ticket_id,
            title=title,
            body=body,
            severity=severity,
            status=astatus,
        ))

    # ── Commit everything ───────────────────────────────────────────────
    db.commit()

    return {
        "project_id": project.id,
        "prefix": DEMO_PREFIX,
        "repo_path": str(DEMO_REPO_DIR),
        "agents": len(agent_objs),
        "epics": len(epic_objs),
        "sprints": len(sprint_objs),
        "tickets": len(ticket_objs),
        "test_results": len(TEST_RESULTS),
        "failure_records": len(FAILURE_RECORDS),
        "alerts": len(ALERTS),
        "doc_files": ["README.md", "INITIAL.md", "ARCHITECTURE.md"],
    }
