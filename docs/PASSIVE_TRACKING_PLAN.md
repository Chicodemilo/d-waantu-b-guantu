# Passive Hook-Based Time & Token Tracking — Implementation Plan

**Date:** 2026-04-09
**Status:** Approved for implementation
**Epic:** Passive Tracking

---

## Problem

Token and time tracking has failed 3 times because it relies on:
1. Agents remembering to POST start/stop/token events (they forget)
2. Users clicking buttons (they don't)
3. A batch transcript scanner on sprint close (too late, too fragile)

The data exists passively in Claude Code transcripts. We need to capture it
automatically via lifecycle hooks. Zero agent awareness. Zero user interaction.

---

## Solution

Claude Code fires lifecycle hooks on session events. We use `SessionStart`,
`SessionEnd`, and `SubagentStop` to POST tracking data to new API endpoints.
The backend parses JSONL transcripts for tokens, resolves agent identity from
transcript metadata, attributes to tickets (workers) or overhead (TL/PM), and
logs everything through the existing `tracking_log` event system.

```
Claude Code Session
  │
  ├─ SessionStart hook ──→ POST /api/hooks/session-start
  │                          → create hook_session record
  │                          → log_start() or log_overhead_start()
  │
  └─ SessionEnd hook ───→ POST /api/hooks/session-end
     SubagentStop hook ─┘    → parse transcript JSONL for tokens + timestamps
                             → resolve agent identity from agentName
                             → resolve ticket (workers) or overhead (TL/PM)
                             → log_stop() + log_tokens() or log_overhead_stop()
```

Rollup chain (already works, computed at query time):
```
tracking_log → Ticket → Agent → Sprint → Epic → Project
```

---

## What We Keep vs Replace

**Keep:**
- `tracking_log` model + event-sourced design
- `tracking.py` service — log_start/stop/tokens, compute_*, get_project_summary
- `tracking.py` router — REST endpoints + summary
- Frontend display components
**Replace:**
- `attribute_tokens.py` (removed) → real-time hook tracking
- `report_tokens.py` (removed) → proper backend service (`hook_tracking.py`)
- `/tmp` state files → `hook_sessions` DB table
- Sprint close auto-scan → real-time hook data
- Manual agent tracking → automatic hook tracking

---

## New Database Table: `hook_sessions`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| session_id | VARCHAR(255) UNIQUE | From hook data |
| transcript_path | TEXT | Full path to JSONL |
| agent_id | FK→agents, nullable | Resolved from transcript |
| project_id | FK→projects | From cwd match |
| ticket_id | FK→tickets, nullable | Null for overhead |
| sprint_id | FK→sprints, nullable | From ticket |
| start_time | DATETIME | |
| end_time | DATETIME, nullable | |
| total_tokens | INT, default 0 | |
| token_breakdown | JSON, nullable | {input, output, cache_creation, cache_read} |
| status | ENUM(active/completed/error) | |
| session_type | ENUM(main/teammate/subagent) | main = overhead |
| agent_name | VARCHAR(255), nullable | Raw from transcript |
| hook_event | VARCHAR(50), nullable | SessionEnd, SubagentStop, etc |
| created_at | DATETIME | |

---

## New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/hooks/session-start` | Receives SessionStart hook data |
| POST | `/api/hooks/session-end` | Receives SessionEnd/SubagentStop hook data |
| GET | `/api/hooks/sessions` | List sessions (filters: project_id, status) |
| GET | `/api/hooks/sessions/{session_id}` | Get session details |

---

## New Service: `hook_tracking.py`

### `handle_session_start(db, hook_data)`
1. Extract session_id, transcript_path, cwd
2. Idempotent check (return existing if found)
3. Resolve project from cwd (match projects.repo_path)
4. Quick-read transcript for agentName
5. Resolve agent, determine session type (main/teammate/subagent)
6. Create HookSession(status=active)
7. Log start: `log_start()` for workers, `log_overhead_start()` for TL/PM

### `handle_session_end(db, hook_data)`
1. Extract session_id, transcript path
2. Find or create HookSession
3. Parse transcript → tokens, timestamps, agent info
4. Resolve agent and work context
5. Log stop + tokens: workers → `log_stop()` + `log_tokens(source="hook")`, overhead → `log_overhead_stop()`
6. Update session: completed, total_tokens, end_time

### `parse_transcript(path)`
Token counting (matches existing logic):
```python
total += usage.get("input_tokens", 0)
total += usage.get("output_tokens", 0)
total += usage.get("cache_creation_input_tokens", 0)
total += usage.get("cache_read_input_tokens", 0)
```

### `resolve_agent(db, agent_name, project_id)`
1. Match by `agent.role == agent_name` (primary)
2. Fallback to name match
3. Scoped to project assignments

### `resolve_work_context(db, agent, project_id)`
- TL/PM → overhead
- Worker → in_progress ticket (fallback: todo, most recently updated)
- No match → unattributed + alert

---

## Hook Configuration (`.claude/settings.json`)

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST http://localhost:8000/api/hooks/session-start -H 'Content-Type: application/json' -d \"$(cat)\" 2>/dev/null || true",
        "timeout": 5
      }]
    }],
    "SessionEnd": [{
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST http://localhost:8000/api/hooks/session-end -H 'Content-Type: application/json' -d \"$(cat)\" 2>/dev/null || true",
        "timeout": 30
      }]
    }],
    "SubagentStop": [{
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST http://localhost:8000/api/hooks/session-end -H 'Content-Type: application/json' -d \"$(cat)\" 2>/dev/null || true",
        "timeout": 30
      }]
    }]
  }
}
```

`|| true` ensures hooks never block Claude Code if API is down.

---

## Frontend Changes

Minimal — existing display components work. Add:

1. **`frontend/src/api/hooks.js`** — API client for hook sessions
2. **`frontend/src/store/useStore.js`** — add hookSessions state + getActiveSessionsByProject getter
3. **`frontend/src/hooks/useAppData.js`** — add hook sessions to polling
4. **`frontend/src/components/project/LiveSessions.jsx`** — pulsing green dot, active agent list with elapsed time
5. **`frontend/src/styles/hooks.css`** — terminal-theme styles
6. **`frontend/src/pages/ProjectPage.jsx`** — wire in LiveSessions component

---

## Team & Sequencing

| Phase | Agent | Work |
|-------|-------|------|
| 1. Model + Migration | @backend-worker | hook_sessions table |
| 2. Schema | @backend-worker | HookEventInput, HookSessionRead |
| 3. Service | @backend-worker | hook_tracking.py — all business logic |
| 4. Router + main.py | @backend-worker | hooks.py endpoints, register |
| 5. Hook config | @backend-worker | .claude/settings.json |
| 6. Sprint close fix | @backend-worker | Remove auto-scan from sprint service |
| 7. Frontend | @frontend-worker | API, store, component, CSS (after Phase 4) |
| 8. Tests | @tester | Full test suite (after Phase 4, parallel with 7) |

---

## Verification

1. Start backend + frontend
2. Open a Claude Code session in the project
3. Dashboard shows "1 active session" on project page
4. End the session
5. `GET /api/hooks/sessions` → completed session with tokens
6. `GET /api/tracking/summary?project_id=1` → time + tokens in rollup
7. `pytest tests/test_hooks.py -v` → all green

---

## Design Decisions

**D1:** hook_sessions is state management, not source of truth. tracking_log remains authoritative.

**D2:** SessionStart must be fast (5s timeout) — only creates a DB record.

**D3:** SessionEnd does heavy lifting (30s timeout) — parses full transcript.

**D4:** SubagentStop routes to same session-end endpoint — same logic, different transcript path field.

**D5:** Endpoints never return 5xx — hooks are fire-and-forget. Errors logged as alerts.

**D6:** Manual scan kept as fallback — batch scanner still works via button/API.
