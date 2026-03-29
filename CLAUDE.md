# D'Waantu B'Guantu — Project Management Dashboard

## What This Is

This is **D'Waantu B'Guantu** (DWB) — a local project management dashboard for monitoring multi-agent workflows, managing team instructions, and tracking token spend.

## Your Role

You are most likely **using this system to track your projects**, not developing the system itself.

- To add a project: use the dashboard at http://localhost:5173 or POST to `/api/projects/from-repo` with your repo path
- To manage a project: create epics, sprints, tickets, and agents through the API or dashboard
- Read QUICKSTART.md to get the system running

## If You ARE Developing This System

If you're making changes to the dashboard itself, read:
- README.md — full system documentation
- ARCHITECTURE.md — technical reference
- INITIAL.md — project requirements and design decisions

## Key Rules

- STOP, PAUSE, or HALT from the user means immediately cease ALL activity. No exceptions.
- Plain CSS only — no Tailwind, no CSS-in-JS. Styles in .css files, never inline.
- No Co-Authored-By or AI attribution in git commits.
- Every sprint must end with a test run (enforced by sprint gates).
- Code headers are mandatory on all files (see /instructions page for format).

## Getting Started

```bash
cp .env.example .env
docker compose up -d
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
cd ../frontend && npm install && npm run dev &
```

Open http://localhost:5173

## API Base URL

http://localhost:8000/api

## Important Endpoints

- POST /api/projects/from-repo — create a project from a repo path
- GET /api/projects/:id/gate-status — check if docs exist
- GET /api/status — system health check
- See README.md for full API reference
