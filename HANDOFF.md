# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-22)

- **Working tree clean. All this-session work committed AND pushed to origin/master** (tip `e96ca02`). Backend 1204→1222 passing, frontend 156→159 passing.
- **Sprint S66 (id=107) still active** (epic 21). It now has **no open tickets** — the epic-21 work (404/405/406) plus carryover 413 and new 414 are all done.
- No open alerts. The system-wide `in_progress: 1` in `/api/status` is **RVP-007 on project 7**, not DWB.

## Shipped this session (5 tickets, 4 commits)

| Ticket | Commit | One-line |
|---|---|---|
| DWB-413 | `58fe262` | `delete_project` clears hook/dwb sessions + consolidation acks in dependency order, and NULLs homed agents' `project_id` (agents are global identities) instead of deleting them. |
| DWB-414 | `b38400a` | Session close-scan scoped to genuine user-authored turns: filters `isMeta`, `toolUseResult`, and synthetic-wrapper string content (teammate-message, command echo/stdout, task-notification, system-reminder, ...) on both open + close. Matched in-memory, no user text persisted. |
| DWB-406 | `9c9cf87` | Dropped unused `anthropic` dep (leftover after DWB-402 retired the AI classifier). |
| DWB-405 | `e96ca02` | `force_headers` missing_files[] now render in the Sprint Gates panel (fetched only while gate is ON, rides existing poll tick). |
| DWB-404 | (doc-only) | Spike resolved: subagents CAN write outside `.claude/` (incl `.dwb/`) with no permission crash. The crash is the `.claude/` permission dialog specifically. |

DWB-414 was the bug the old handoff loosely called "DWB-396" — that key was never filed; Pam filed it fresh as DWB-414 in S66.

## Carryover (pre-existing, NOT from this session)

- **10 stale backlog/todo tickets** on project 1, all in old sprints (49, 65, 102, 20, 23) — long-standing backlog, not active work. (DWB-051 Jira research, DWB-192-196/227-228 token/time audits, DWB-316 inbox viewer, DWB-066 auto-assign.)
- **6 open failure records** (sprint 38 from March, sprint 107 from 2026-06-10; agents Sage/Sylvie/Barry). They predate this session and would only block an S66 sprint-close — harmless to a restart, but clear them before closing S66.

## Team

- This session spawned Pam_DWB (14, PM), Barry_DWB (21, backend), **Stan (38, backend — NEW, created this session)**, Freddie (19, frontend). All parked alive at session end; respawn before use, do NOT SendMessage cold names.

## Gotchas (carry forward)

- **Synthetic user-role turns:** CC records tool results, teammate-message relays, command echoes, task-notifications, and system-reminders all with role=`user`. Anything scanning the transcript for "what the human typed" MUST filter these (see `_is_synthetic_user_text` / `_SYNTHETIC_USER_TAGS` in `hook_tracking.py`).
- **delete_project FK order:** child rows (hook_sessions → dwb_sessions → consolidation_acks → tickets → project_agents) must clear before parents; homed agents get detached (NULL project_id), never deleted.
- **`.claude/` Edit by subagent = crash** (permission dialog). Only the TL edits `.claude/`. Writes to `.dwb/` and ordinary project files are safe (DWB-404).
- **Verify worker liveness** (`presumed_live`/`last_seen` on `/team`) before assuming a worker is building.
- **`GET /api/alerts?status=open` is NOT project-scoped** — pass `project_id`. Same for `/api/status` and `/failure-records/summary`, which are system-wide across all projects.
- **Doc ceilings** (`backend/app/config/token_budget.py`): HANDOFF 1500, ARCHITECTURE 7500, README 3500.
