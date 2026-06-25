# Quick Start

## For Humans

```bash
git clone https://github.com/your-org/d-waantu-b-guantu.git
cd d-waantu-b-guantu
claude
```

Then paste:

```
you are archie, read your playbook. We'll be using D'Waantu B'Guantu to
track our projects. Bring up the dashboard, create my first project, and
report back when it is running.
```

Archie reads the repo, runs the setup, creates your first project, and reports back ready for work. That opening phrase also opens a tracked DWB session, so time and tokens are attributed from the start.

Prefer to bring it up yourself? Follow the numbered steps below, then open the in-app Help Center at http://localhost:5173/help for the full quick-start flow and per-view help.

## For Agents

You're an agent and you landed here? Here's what to read:

1. **CLAUDE.md** - project rules, API reference, hierarchy (auto-loaded)
2. **Your agent def** - `.claude/agents/{your-role}.md` (auto-loaded)
3. **Your playbook** - `docs/{role}_playbook.md` is the **canonical source**; `.claude/{role}_playbook.md` is the **deployed copy** that `POST /api/projects/{id}/deploy-playbooks` writes into each target repo. Edits should land in `docs/` and be re-deployed; never edit the deployed `.claude/` copy directly.
4. **HANDOFF.md** - last session's state plus what's next. **Team-lead only.** Workers and the PM rely on their own memory dir (`.dwb/memory/<PREFIX>/<Name>/`, holding a system-generated `identity.md` and a single free-form `memory.md`; DWB-401 collapsed the former scratchpad/lessons/recent_sessions into `memory.md`) plus the TL's brief, not HANDOFF. Read `ARCHITECTURE.md` / `README.md` only if your task is cross-cutting and the TL points you there; never create or maintain root-level docs.
5. **Team roster** - `GET /api/projects/{id}/team` is the **DB-authoritative roster**. The old checked-in `TEAM.md` file was removed in DWB-312 (2026-06-05); the LiveSessions panel and any agent that needs the roster reads from the API. Don't grep for or write to TEAM.md, it isn't there.

### Agent identity flow at spawn

1. The TL pre-writes a pending marker at `.claude/agents/active/pending-<agent_id>-<unix_ms>-<rand4hex>` with JSON content `{"agent_id": N, "agent_name": "...", "role": "...", "project_prefix": "DWB"}`.
2. When the spawned teammate's session starts, it calls `POST /api/agents/identify` with `{role, name, project_prefix}` and receives its `agent_id` plus `memory_dir`. Names accept the short form (`Archie`) or the system-unique `_<PREFIX>` form (`Archie_DWB`), see DWB-315.
3. The teammate reads its memory dir at `.dwb/memory/<PROJECT_PREFIX>/<Name>/` and writes notes through the memory API (`POST /api/agents/{id}/memory/append`); the resolver renames the pending marker to the CC session id on first SubagentStop. Subagents must never write under `.claude/` directly.
4. Hooks fire on session boundaries; tokens are attributed to the resolved `agent_id` without further work from the teammate.

---

**Prerequisites:** Docker, Node.js 18+, Python 3.12+

---

## 1. Clone and configure

```bash
git clone <repo-url> && cd d-waantu_b-guantu
cp .env.example .env
```

No changes needed, the `.env` defaults work out of the box.

## 2. Start the database

```bash
docker compose up -d
```

Wait for healthy status:

```bash
docker compose ps
```

**What you'll see:** Two containers, `lat_mysql` (port 23847) and `lat_phpmyadmin` (port 8080), both showing "running" / "healthy". MySQL may take 10-15 seconds to become healthy on first run.

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

**What you'll see:** Vite prints `Local: http://localhost:5173/`. The dashboard loads but will be empty until you create or seed a project. Leave this terminal running.

## 5. Open the dashboard

Open http://localhost:5173 in your browser.

**What you'll see:** The cross-project dashboard with a summary, open alerts, project cards, token usage, and the agents table. Click into a project to see sprints, epics, tickets, test results, and agent activity.

**In-app help:** Visit http://localhost:5173/help for the living quick-start flow and per-view help. The `/help` quick-start is the canonical, always-current version of this document; if the two ever disagree, trust `/help`.

## 6. Get data on the board

Two ways to populate the dashboard:

- **Seed a demo (fastest):** on the dashboard, click `$ seed demo project`, or call `POST /api/projects/seed-demo`. This creates a fully populated demo project so you can explore every view with realistic data. Delete it once you start tracking real work.
- **Track a real repo:** click `$ add project` and enter a repo path, or call `POST /api/projects/from-repo` with `{"repo_path": "/path/to/repo"}`. It auto-detects the name, prefix, and description from the repo.

---

## Ports

| Service    | Port  | URL                          |
|------------|-------|------------------------------|
| Frontend   | 5173  | http://localhost:5173        |
| API        | 8000  | http://localhost:8000        |
| API Docs   | 8000  | http://localhost:8000/docs   |
| Help       | 5173  | http://localhost:5173/help   |
| MySQL      | 23847 | (direct connection)          |
| phpMyAdmin | 8080  | http://localhost:8080        |

## Run tests

```bash
cd backend && source .venv/bin/activate
pytest tests/ -v
```

## Token tracking

Token and time tracking is **automatic** via Claude Code lifecycle hooks, no manual steps needed. When agents work, hooks fire (`SessionStart`, `SessionEnd`, `SubagentStop`) and attribute tokens to the correct ticket (workers) or the project's `tl_overhead_tokens` / `pm_overhead_tokens` buckets (TL/PM). Hook config lives in `.claude/settings.json`.

There is no manual backfill endpoint; the hook pipeline plus the `_parse_subagent_from_projects_dir` fallback (DWB-311, scans the CC projects dir when the synthetic transcript path is missing) cover all real attribution paths. To inspect stale or unattributed sessions, use `GET /api/hooks/sessions?status=orphan&cutoff_minutes=60`.

## Troubleshooting

- **"Can't connect" on MySQL:** Containers need 10-15 seconds on first start. Run `docker compose ps` and wait until mysql shows "healthy".
- **`python: command not found`:** Use `python3` instead. On macOS, `python` may not be aliased.
- **Empty dashboard:** Create or seed a project (step 6). Hard-refresh (Cmd+Shift+R) if needed; the frontend auto-polls.
- **Port conflict:** Edit `.env` to change ports. `MYSQL_PORT`, `API_PORT`, `PMA_PORT`, and `VITE_API_BASE_URL` are all configurable.
