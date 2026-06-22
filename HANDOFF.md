# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-22)

- **Epic 25 "Semantic Event System" COMPLETE (6/6) and COMMITTED** as `db75945` (feat(events): semantic activity event system with type-aware feed renderer). Working tree clean.
- **Sprint S66 (id=107) still active**, epic 21 in_progress (untouched: DWB-404 spike in_progress, 405/406 backlog).
- Epic 25 / sprint S67 (id=115, planned) holds the event tickets 407-412 (all done).
- Backend 1204 passing, frontend 156 passing.

## Epic 25 — what shipped

8 semantic domain verbs emitted from the service layer via a canonical `log_activity()` helper, disjoint from generic middleware CRUD verbs, with read-side feed dedup by action-class pairing (`SEMANTIC_GENERIC_SHADOWS`, NOT a bare time window). Feed renders all 8 as human phrases.

| Ticket | One-line |
|---|---|
| DWB-407 | Type-aware live ProjectPage feed (ticket/alert/sprint links). |
| DWB-408 | Canonical `log_activity()` helper + disjoint MIDDLEWARE/SEMANTIC actions. |
| DWB-409 | Ticket verbs: status_changed{from,to}, assigned, reopened. Actor = X-Agent-ID. |
| DWB-410 | sprint_opened/closed + consolidation_acked; retired the ack URL hack. |
| DWB-411 | session_opened/closed (entity_type `session`). |
| DWB-412 | Feed renderer extended for all 8 verbs; bare {from,to} ticket rows fall back to "ticket #id". |

## Carryover (backlog, out of epic 25 scope)

- **DWB-413:** delete_project 500s on projects with acks/agents/sessions. Cascade-clear child rows before delete.
- **DWB-396:** prose-false-close still open. Transcript close-scan fires on example/quoted text; needs scoping to user-authored turns (bit session 26 + 32).

## Team

- Freddie (19, frontend) spawned + parked alive this session. Barry (21), Pam (14), others DOWN. Respawn before use; do NOT SendMessage cold names.

## Gotchas (carry forward)

- **Verify worker liveness** (`presumed_live`/`last_seen` on `/team`) before assuming a worker is building.
- **`.claude/` Edit by subagent = crash.** Only the TL edits `.claude/` files. Worker memory goes through the API.
- **No-double-log rule:** semantic verbs disjoint from middleware verbs; feed dedup suppresses the generic sibling on the read side only (both rows stay in the DB).
- **Doc ceilings** (`backend/app/config/token_budget.py`): HANDOFF 1500, ARCHITECTURE 7500, README 3500.
- **`GET /api/alerts?status=open` is NOT project-scoped** — pass `project_id`.
