# Quick Start

## For Humans

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

Archie reads the repo, runs the setup, creates your first project, and reports back ready for work.

## For Agents

You're an agent and you landed here? Here's what to read:

1. **CLAUDE.md** — project rules, API reference, hierarchy (auto-loaded)
2. **Your agent def** — `.claude/agents/{your-role}.md` (auto-loaded)
3. **Your playbook** — `docs/{role}_playbook.md` is the **canonical source**; `.claude/{role}_playbook.md` is the **deployed copy** that `POST /api/projects/{id}/deploy-playbooks` writes into each target repo. Edits should land in `docs/` and be re-deployed; never edit the deployed `.claude/` copy directly.
4. **HANDOFF.md** — what happened last session, what needs doing next
5. **Team roster** — `GET /api/projects/{id}/team` is the **DB-authoritative roster**. The old checked-in `TEAM.md` file was removed in DWB-312 (2026-06-05); the LiveSessions panel and any agent that needs the roster reads from the API. Don't grep for or write to TEAM.md — it isn't there.

### Agent identity flow at spawn

1. The TL pre-writes a pending marker at `.claude/agents/active/pending-<agent_id>-<unix_ms>-<rand4hex>` with JSON content `{"agent_id": N, "agent_name": "...", "role": "...", "project_prefix": "DWB"}`.
2. When the spawned teammate's session starts, it calls `POST /api/agents/identify` with `{role, name, project_prefix}` and receives its `agent_id` + `memory_dir`. Names accept the short form (`Archie`) or the system-unique `_<PREFIX>` form (`Archie_DWB`) — see DWB-315.
3. The teammate writes its session-id marker locally (or relies on the resolver to rename the pending marker on first SubagentStop) and reads its memory dir at `.claude/agents/memory/<PROJECT_PREFIX>/<Name>/`.
4. Hooks fire on session boundaries; tokens are attributed to the resolved `agent_id` without further work from the teammate.

---

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
mysql -h 127.0.0.1 -P 23847 -u lat_user -plat_dev_password local_agent_tracker < seed_demo.sql
```

**What you'll see:** No output means success. If you get `ERROR 2003 (HY000): Can't connect`, MySQL is still starting — wait a few seconds and retry.

`seed_demo.sql` is a minimal touring dataset — one project, three agents, one sprint, four tickets — enough to see the dashboard populated. Delete or replace it once you start tracking real work.

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

Token and time tracking is **automatic** via Claude Code lifecycle hooks — no manual steps needed. When agents work, hooks fire (`SessionStart`, `SessionEnd`, `SubagentStop`) and attribute tokens to the correct ticket (workers) or the project's `tl_overhead_tokens` / `pm_overhead_tokens` buckets (TL/PM). Hook config lives in `.claude/settings.json`.

There is no manual backfill endpoint — the hook pipeline + the `_parse_subagent_from_projects_dir` fallback (DWB-311, scans the CC projects dir when the synthetic transcript path is missing) cover all real attribution paths. If you have stale or unattributed sessions, inspect them via `GET /api/hooks/sessions?status=orphan&cutoff_minutes=60` and clean up with `DELETE /api/test-results/{id}` or the activity-log audit.

## Troubleshooting

- **"Can't connect" on MySQL:** Containers need 10–15 seconds on first start. Run `docker compose ps` — wait until mysql shows "healthy".
- **`python: command not found`:** Use `python3` instead. On macOS, `python` may not be aliased.
- **Empty dashboard after seeding:** Hard-refresh (Cmd+Shift+R). The frontend auto-polls every second.
- **Port conflict:** Edit `.env` to change ports — `MYSQL_PORT`, `API_PORT`, `PMA_PORT`, and `VITE_API_BASE_URL` are all configurable.
