# CHANGELOG

## 2026-04-09 — BREAKING: Directory + Repo Rename

### READ THIS FIRST IF ANYTHING LOOKS WRONG

**The project has been renamed everywhere.**

| What | Before | After |
|------|--------|-------|
| **Directory** | `/Users/mchick/Dev/local_agent_tracker` | `/Users/mchick/Dev/d-waantu_b-guantu` |
| **GitHub repo** | `MilesVTG/local-agent-tracker` | `MilesVTG/d-waantu-b-guantu` |
| **Claude project dir** | `~/.claude/projects/-Users-mchick-Dev-local-agent-tracker` | `~/.claude/projects/-Users-mchick-Dev-d-waantu-b-guantu` |

**Why:** Agents were confusing the app name (D'Waantu B'Guantu / DWB) with
the old directory name (local_agent_tracker). The directory name now matches
the application identity.

### If you are an agent mid-session and your working directory is gone

Your `cwd` pointed at `/Users/mchick/Dev/local_agent_tracker` which no
longer exists. Here's what to do:

1. **Stop what you're doing** — any file writes to the old path will fail
2. **Re-orient:** the repo is now at `/Users/mchick/Dev/d-waantu_b-guantu`
3. **Update your git remote** if needed:
   ```bash
   git remote set-url origin https://github.com/MilesVTG/d-waantu-b-guantu.git
   ```
4. All code, branches, history, and database are intact — only the paths changed

### What did NOT change

- **MySQL database name** remains `local_agent_tracker` — this is the DB name, not the app name
- **DWB project prefix** remains `DWB`
- **All API endpoints, ports, and behavior** are unchanged
- **Docker containers** (`lat_mysql`, `lat_phpmyadmin`) are unchanged
- **All branches and git history** are preserved

### Files updated in this rename

- `seed.sql` — repo_path
- `backend/scripts/attribute_tokens.py` — transcript dir matching (legacy patterns kept as fallback)
- `backend/app/services/sync_check.py` — MEMORY_DIR path
- `docs/team_lead_playbook.md` + `.claude/team_lead_playbook.md` — repo_path examples
- `README.md`, `PLAN.md`, `QUICKSTART.md`, `ARCHITECTURE.md` — directory references

### If you have stale references in your context

Search for `local_agent_tracker` or `local-agent-tracker` and replace
path references with `d-waantu_b-guantu` / `d-waantu-b-guantu`.
