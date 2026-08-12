# CHANGELOG

## 2026-08-12 — Standards Auditor (sprints 23–24)

The self-enforcing standards-audit system, end to end.

- **Fresh-auditor pipeline:** `scripts/run_standards_audit.sh` → `standards_audit.py` spawns a context-starved headless `claude -p` judged only on the global standards sheet + the repo's `## Project Extensions` + the diff, against a strict-JSON contract. Malformed output is never posted.
- **Storage + API:** new `standards_audit` table and `/api/standards-audits` (record verdict/violations/scorecard), plus an explicit idempotent `/{id}/apply-scorecard` that writes to the `score_event` ledger (`source=audit`, `audit_grant`/`audit_demerit`, bypassing peer caps).
- **The_Auditor** system agent (id 51, `project_id` NULL) seeded via migration dwb028; owns audit ledger rows and activity-feed attribution.
- **Visibility:** every audit raises an alert (info=pass, warning=reject) + feed entry; new **Audits page** at `/projects/:id/audits` with pass/fail stats and expandable rows; shared verdict/violations/scorecard components under `components/common/`.
- **Gate:** `force_standards_audit` blocks sprint close without a passing audit in-window. `force_coding_standards_md` (doc-exists) enabled across projects.
- **Token attribution fix (DWB-022):** per-ticket token writes are now atomic (ledger event + cache in one commit), attributed via `X-Agent-ID`/assignee, with a real `token_source`. Migration dwb022 reconciled 10 orphan tickets (~550k phantom tokens → `source='reconciled'`).

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
