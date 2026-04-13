# Handoff — 2026-04-09

## Known Bugs (not yet ticketed)

### DELETE /api/tickets/{id} returns 500 — missing FK cascade (discovered 2026-04-13)
The delete endpoint fails on every ticket because child tables reference `tickets.id` without `ON DELETE CASCADE` on the FK and without `cascade="all, delete-orphan"` on the SQLAlchemy relationships.

Affected child tables: `status_history`, `comments`, `alerts`, `test_results`, `failure_records`, `tracking_log`, `hook_sessions`.

Workaround used 2026-04-13: direct SQL against `local_agent_tracker` DB to clean up 17 orphaned CI dupes. See Claims Images repo reports/dwb_orphans_2026-04-13.md for the deleted ticket list.

Fix: add `cascade="all, delete-orphan"` to the `Ticket.relationship(...)` declarations for each child, OR set `ondelete="CASCADE"` on the FK columns and use `passive_deletes=True` on the relationships. Needs a DWB + Jira ticket before touching.

### TicketStatus enum has no `won't_do` value (discovered 2026-04-13)
The `TicketStatus` enum in `app/models/ticket.py` only allows `backlog | todo | in_progress | in_review | done`. There's no way to mark a ticket as "closed but not delivered" — tickets closed as Won't Do get set to `done` as the least-bad proxy. Sprint metrics can't distinguish closed-delivered from closed-not-delivered without filtering by Jira mirror state or by comment content.

Workaround used 2026-04-13: CI-085 / POR-5394 closed `status=done` with a comment documenting the Won't Do rationale; Jira side carries the true "Won't Do" state via `dwb2jira ticket transition --to "Won't Do"`.

Fix: add `won_t_do` (or `cancelled`) to the `TicketStatus` enum, migration to allow the new value, update any status-filtering queries that assumed the old enum set.

## What happened this session

### 1. Directory + repo rename
`local_agent_tracker` renamed to `d-waantu_b-guantu` everywhere:
- Directory, GitHub repo (`MilesVTG/d-waantu-b-guantu`), Claude project settings dirs
- All hardcoded path references in code + docs
- MySQL DB name stays `local_agent_tracker` (infrastructure, not identity)
- CHANGELOG.md created at repo root with agent recovery instructions
- See commit `bc09559`

### 2. Passive hook-based tracking (Sprint 43)
Replaced the broken manual token/time tracking with automatic Claude Code lifecycle hooks. This was the big one — tried and failed 3 times before. Now it's fully passive.

**How it works:**
- `.claude/settings.json` defines hooks for SessionStart, SessionEnd, SubagentStop
- Hooks curl `POST /api/hooks/session-start` and `POST /api/hooks/session-end`
- Backend parses JSONL transcripts for tokens (message.usage), resolves agent from agentName field
- Workers get time+tokens on their in_progress ticket; TL/PM get overhead
- `hook_sessions` table tracks session state; `tracking_log` stays the authoritative ledger

**Key files:**
- `backend/app/services/hook_tracking.py` — all business logic
- `backend/app/routers/hooks.py` — 4 endpoints
- `backend/app/models/hook_session.py` — session state model
- `.claude/settings.json` — hook configuration
- `docs/PASSIVE_TRACKING_PLAN.md` — full design doc

**Bugs found and fixed:**
- `parse_transcript()` was looking at `entry["usage"]` but transcripts nest it at `entry["message"]["usage"]` — fixed to check both
- `handle_session_end()` wasn't re-resolving agent when session start had no transcript data yet — now re-reads transcript and resolves on end

**What's NOT done yet:**
- Mid-session token updates (would need a `Stop` hook firing after each response — v2)
- The `datetime.utcnow()` deprecation warnings (9 of them) — trivial, just swap to `datetime.now(datetime.UTC)`

### 3. Terminal output viewer for test results
- Clickable test run rows expand to show terminal-style output with ASCII borders (`+---+`, `|`)
- Animated open/close, 220px max height, scrollable, full-width borders
- "$ run system tests" button actually runs tests now (was just creating an alert before)
- Output stored in test result `details.raw_output_tail`
- Works on both `/tests` (global) and `/projects/:id/tests` pages

### 4. Stale test fixes
- 3 response shape tests were failing (missing `jira_project_key`, `jira_issue_key`, `infra_warnings` fields) — fixed

## Current state
- **391 tests, 0 failures**
- **Frontend build clean**
- **API running** from new directory (uvicorn restarted this session)
- **Vite dev server** may need restart — was killed/restarted during session
- **2 hook sessions captured** but with 0 tokens (pre-bugfix). Future sessions will capture correctly.

## Unstaged changes in working tree
These files were modified before this session and never committed:
- `frontend/src/components/tickets/TicketDetail.jsx`
- `frontend/src/components/tickets/TicketList.jsx`
- `frontend/src/styles/common.css`
- `frontend/src/styles/tickets.css`

Ask the user what these are before committing them.

## Active sprint in DWB
Sprint 43 "Passive Hook-Based Time And Token Tracking" (id=63) under Epic 14 "Passive Hook Tracking". 8 tickets (DWB-219 through DWB-226), all should be closeable.

## What to work on next
1. Verify hooks are capturing tokens correctly (end this session, check hook_sessions table)
2. Frontend display of time/tokens on dashboard — data should be flowing now
3. Consider adding `Stop` hook for mid-session incremental token updates
4. The unstaged ticket UI changes in the working tree
