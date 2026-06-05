# Handoff — D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State

**Sprint 64 active** (id=105, "Test sprint — verify consolidation gate bites on over-ceiling files"). 623 backend tests passing.

Smoke ticket: DWB-330 (id=807) — Barry added a header comment to `backend/scripts/migrate.sh:2`. In_review.

S63 closed 2026-06-05 with 4 tickets: DWB-326 (participant scoping), DWB-327 (ceiling rebalance + trims), DWB-328 (gate teeth — ack endpoint refuses over-ceiling files), DWB-325 carry from S62.

## Active Decisions

- **Passive hook-based token tracking** via `.claude/settings.json` hooks (SessionStart/End/SubagentStop).
- **Marker format = JSON dict** at `.claude/agents/active/<session_id>`. TL pre-writes `pending-<agent_id>-<unix_ms>-<rand4hex>`; resolver renames on first SubagentStop (DWB-304).
- **System-wide unique agent names** (DWB-315): `UNIQUE(name)`. Fixed roles use `_<PREFIX>` suffix.
- **DB-authoritative roster** (DWB-312): no TEAM.md. `GET /api/projects/{id}/team`.
- **No PM for small teams** (≤2 workers).
- **TL writes `.claude/` files on workers' behalf** (subagent + `.claude/` write crashes CC).
- **Pam Jira limits** (DWB-323/324): PM can never `dwb2jira sprint close/create/edit/delete`. CLI refuses exit 1.
- **Consolidation gate has teeth** (DWB-328): ack endpoint returns 400 if owned files are over ceiling, unless per-file overrides with non-empty reasons are provided. Audit trail in `overrides` JSON column on `agent_consolidation_acks`.
- **Participants for sprint** (DWB-326): required-ack set = agents with ticket / comment / tracking_log / hook_session / activity_log activity in the sprint window.

## Gotchas

- Alembic autogenerate misses MySQL enum changes — write manual migrations.
- `tickets.find()` returns first match — sort by `updated_at desc` for in_progress.
- SubagentStop's `agent_transcript_path` points at a synthetic path; fallback scans parent session's projects-dir `.jsonl` filtered by `agentName` (DWB-311).
- `agent_type` in SubagentStop payload is empty string in practice — don't role-match on it.
- Stale `.pyc` cache can mask real test failures — `find backend -name __pycache__ -exec rm -rf {} +` before reporting test counts.
- DWB-329 (backlog): participants_for_sprint counts TL admin acks; refine signal to exclude consolidate-complete activity.

## Backlog

- DWB-316 — CC inbox viewer for dashboard
- DWB-329 — Refine participants_for_sprint to exclude admin acks
- Active consolidation work (system drives the trim, not just demands it)

## Last 3 Sprints

**S63 — Gate enforcement + ceiling rebalance (closed 2026-06-05).** 4 tickets. Participant scoping (326), ceiling rebalance + trims (327), gate teeth (328). The gate is now a wall: Barry's first ack attempt was REFUSED with violations; after cap rebalance dropped his files under, retry passed clean.

**S62 — Force_team_md retire + Pam safety guards (closed 2026-06-05).** 5 tickets. force_team_md ripped, consolidation gate audited + canary, Pam safety in 4 files + D2J CLI guard (25 new tests), consolidation gate documented in 6 files.

**S61 — Doc audit + sync (closed 2026-06-05).** 4 tickets. 38 stale items across 13 files synced to S59+S60 reality.
