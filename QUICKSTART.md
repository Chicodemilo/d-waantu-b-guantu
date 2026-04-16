# Quick Start

Get a working dashboard with sample data in under 5 minutes.

**Prerequisites:** Docker, Node.js 18+, Python 3.12+, mysql client (`brew install mysql-client` on macOS)

---

## 1. Clone and configure

```bash
git clone <repo-url> && cd d-waantu_b-guantu
cp .env.example .env
```

No changes needed — `.env` defaults work out of the box.

## 2. Start the database

```bash
docker compose up -d
```

Wait for healthy status:

```bash
docker compose ps
```

**What you'll see:** Two containers — `lat_mysql` (port 23847) and `lat_phpmyadmin` (port 8080) — both showing "running" / "healthy". MySQL may take 10–15 seconds to become healthy on first run.

## 3. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**What you'll see:** Alembic applies migrations, then uvicorn prints `Uvicorn running on http://127.0.0.1:8000`. Visit http://localhost:8000/docs to see the Swagger API docs. Leave this terminal running.

## 4. Start the frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

**What you'll see:** Vite prints `Local: http://localhost:5173/`. The dashboard loads but will be empty until you seed data. Leave this terminal running.

## 5. Seed sample data (new terminal)

From the repo root:

```bash
mysql -h 127.0.0.1 -P 23847 -u lat_user -plat_dev_password local_agent_tracker < seed.sql
```

**What you'll see:** No output means success. If you get `ERROR 2003 (HY000): Can't connect`, MySQL is still starting — wait a few seconds and retry.

## 6. Open the dashboard

Open http://localhost:5173 in your browser.

**What you'll see:** Dashboard with project cards showing ticket counts, token usage, and time spent. Click into a project to see sprints, epics, tickets, test results, and agent activity.

---

## Ports

| Service    | Port  | URL                          |
|------------|-------|------------------------------|
| Frontend   | 5173  | http://localhost:5173        |
| API        | 8000  | http://localhost:8000        |
| API Docs   | 8000  | http://localhost:8000/docs   |
| MySQL      | 23847 | (direct connection)          |
| phpMyAdmin | 8080  | http://localhost:8080        |

## Run tests

```bash
cd backend && source .venv/bin/activate
pytest tests/ -v
```

## Token tracking

Token and time tracking is **automatic** via Claude Code lifecycle hooks — no manual steps needed. When agents work, hooks fire and attribute tokens to tickets.

To manually backfill or recover tokens from transcripts:

```bash
curl -X POST http://localhost:8000/api/projects/1/scan-tokens
```

**What you'll see:** JSON with `sessions_found`, `sessions_attributed`, and `total_tokens`.

## Troubleshooting

- **"Can't connect" on MySQL:** Containers need 10–15 seconds on first start. Run `docker compose ps` — wait until mysql shows "healthy".
- **`python: command not found`:** Use `python3` instead. On macOS, `python` may not be aliased.
- **Empty dashboard after seeding:** Hard-refresh (Cmd+Shift+R). The frontend auto-polls every second.
- **Port conflict:** Edit `.env` to change ports — `MYSQL_PORT`, `API_PORT`, `PMA_PORT`, and `VITE_API_BASE_URL` are all configurable.
