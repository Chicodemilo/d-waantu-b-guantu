# Quick Start

Get a working dashboard with sample data in under 5 minutes.

**Prerequisites:** Docker, Node.js 18+, Python 3.12+

---

## 1. Clone and configure

```bash
git clone <repo-url> && cd local_agent_tracker
cp .env.example .env
```

No changes needed in `.env` for local dev — defaults work out of the box.

## 2. Start the database

```bash
docker compose up -d
```

**What you'll see:** Two containers start — MySQL on port 23847 and phpMyAdmin on port 8080. Run `docker compose ps` to confirm both show "running".

## 3. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**What you'll see:** Alembic runs migrations, then uvicorn starts with `Uvicorn running on http://127.0.0.1:8000`. Visit http://localhost:8000/docs to confirm — you should see the Swagger API docs.

## 4. Start the frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

**What you'll see:** Vite starts with `Local: http://localhost:5173/`. The dashboard loads but will be empty until you seed data.

## 5. Seed sample data (new terminal)

```bash
cd local_agent_tracker
mysql -h 127.0.0.1 -P 23847 -u lat_user -plat_dev_password local_agent_tracker < seed.sql
```

**What you'll see:** No output means success. If you get a connection error, wait a few seconds for MySQL to finish starting and retry.

## 6. Open the dashboard

Open http://localhost:5173 in your browser.

**What you'll see:** The dashboard with sample project data — project cards with ticket counts, token usage, time spent. Click into a project to see sprints, epics, tickets, test results, and agent activity.

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

**What you'll see:** Test results with pass/fail counts. All tests should pass on a fresh setup.

## Scan tokens from transcripts

After seeding data, you can scan Claude session transcripts to attribute token usage to tickets:

```bash
curl -X POST http://localhost:8000/api/projects/1/scan-tokens
```

**What you'll see:** JSON response with `sessions_found`, `sessions_attributed`, and `total_tokens` — showing how many sessions were matched to tickets.

## Troubleshooting

- **"Connection refused" on MySQL:** Docker containers may need a few seconds after `docker compose up -d`. Wait and retry.
- **Empty dashboard after seeding:** Hard-refresh the browser (Cmd+Shift+R). The frontend polls for data every few seconds.
- **Port conflict:** If 5173, 8000, or 23847 are in use, check `.env` and `docker-compose.yml` for port configuration.
