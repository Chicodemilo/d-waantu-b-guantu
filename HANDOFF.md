# Handoff — D'Waantu B'Guantu

> Session-to-session continuity notes. Read this at the start of every session. Update it at the end.

## Current State

Sprint 54 complete (investigation). Sprint 55 planned but not yet created — waiting on user approval. Team is up: Archie, Pam, Barry, Freddie on team dwb-s52. 426 backend tests passing.

## Active Decisions

- Passive hook-based token tracking (Sprint 43) — no manual token reporting
- SubagentStop now handled correctly — separate `_handle_subagent_stop()` creates teammate sessions keyed on `agent_id`, not parent `session_id`
- Plain CSS only, terminal aesthetic
- PM is mandatory on every team
- Teams stay alive until user says to shut down
- MySQL DB name stays `local_agent_tracker` (legacy, not changing)
- `.claude/agents/` = local Claude Code agent defs for this repo
- `docs/` = deployable playbooks pushed to other projects via deploy-playbooks
- TEAM.md = live roster (dynamic, grows as team spins up)
- HANDOFF.md = session continuity (this file)
- **Team Status panel is ticket-status driven** — agent shows "working" if they have an in_progress ticket. No hooks, no manual registration. Deterministic.
- **TL orchestrates only** — never writes code, edits files, or makes direct fixes. Delegates everything to workers, reviews their output.
- **Playbooks vs project rules**: playbooks are generic (overwritten on deploy), project rules are project-specific (never overwritten). 6 files total per project.
- **DWB is private** — never mention DWB in Jira, PRs, commits, or external content. Generalized for all human users, not just Miles.
- **Alert triage is a TL core duty** — check `GET /api/alerts?status=open` and `.claude/ALERTS_PENDING.md` at natural cadence points (after ticket close, teammate idle, sprint transitions, human message). ALERTS_PENDING.md takes priority.
- **Dashboard alerts are read-only** — table with Project/Severity/Title/Created. Actions (dismiss, send to team) live on ProjectPage only.

## Gotchas

- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for enum ALTER
- Frontend vitest has 23 pre-existing mock failures (`response.text is not a function`) — not blocking
- `deploy-playbooks` pushes TL, PM, and worker playbooks from `docs/` + creates blank project rules files
- Demo seed creates fake repo at `/tmp/dwb-demo-project` — must include all gated doc files
- Deploy is destructive on playbooks — always re-deploy after committing changes to `docs/`
- `tickets.find()` returns first match — sort by updated_at desc when picking in_progress tickets
- Hook sessions exist for the main session (TL) but teammates don't trigger SessionStart hooks — SubagentStop is the teammate tracking path
- SubagentStop sends different field names than SessionEnd (agent_type, agent_id, agent_transcript_path, hook_event_name) — handled by `_handle_subagent_stop()` in hook_tracking.py
- `|| true` on hook commands swallows errors silently — if token tracking breaks, check the hook command output first

## Known Bugs

None currently open.

## What Needs Doing Next

1. **Sprint 55 — Fix token/time display across frontend and backend** (approved plan, tickets not yet created):
   - DWB-272: Hooks increment ticket.tokens_used and project overhead on token attribution (Barry). In hook_tracking.py, after `tracking.log_tokens()` calls in both `_handle_subagent_stop` and `handle_session_end`, also increment `ticket.tokens_used`. Same for project overhead fields.
   - DWB-273: Enrich per_ticket tracking summary response with `title` and `assigned_agent_id` — TimeTokens breakdown needs these fields (Barry)
   - DWB-274: Fix all frontend field name mismatches (Freddie). 6 root causes across 16 display points:
     - `.time` → `.time_seconds` in 6 components (ProjectHeader, ProjectCard, CrossProjectSummary, TimeTokens, SprintProgress, EpicList)
     - `.tokens_used` → `.tokens` and `.time_spent_seconds` → `.time_seconds` in TimeTokens per_ticket breakdown
     - `.tokens` → `.total_tokens` in TokenAudit agent rows
     - `.overhead_tokens` → sum of `.tl_overhead` + `.pm_overhead` in TokenAudit project rows
   - DWB-275: Render OverheadTracker on ProjectPage or remove dead import (Freddie)
   - Dependency: DWB-273 should complete before the TimeTokens part of DWB-274
2. **Token efficiency** — investigate ways to lighten token usage when using the DWB system
3. **Update HANDOFF.md at CI project** — may reference dead register/deregister endpoints

## Last Session (2026-04-17)

### Sprint 53 — Doc Updates for Token Attribution Fix
- Updated 6 doc files (ARCHITECTURE, playbooks, agent defs) to reflect expanded _resolve_ticket lookup chain (in_progress > todo > in_review > done within 5 min)
- Single-ticket sprint (DWB-269)

### Sprint 54 — Investigate Token/Time Display Gaps
- Freddie audited all 16 frontend display points for tokens/time — found 6 field name mismatches and 1 backend data population gap
- Barry audited backend data chain — hook_sessions have 120M tokens logged, but tracking.log_tokens() never increments ticket.tokens_used. Only 2 token_report events in tracking_log for worker sessions.
- Root cause: two layers — (1) hooks don't write to ticket fields, (2) frontend reads wrong property names from API responses
- DWB-270 (frontend audit) and DWB-271 (backend audit) both done

### Sprint 52 — Token Attribution Fix
- Fixed `_resolve_ticket()` in hook_tracking.py — was only checking `in_progress` and `todo`, now checks `in_review` and `done` (within 5 min)
- Root cause of all zero-token tickets reported by CI team: workers move tickets to `in_review` before SubagentStop fires, so token attribution found nothing
- Updated 6 doc files (ARCHITECTURE, playbooks, agent defs) to reflect expanded lookup chain
- Single-ticket sprint (DWB-268)

### Sprint 48 — Cleanup
- Removed dead register-agent and deregister-agent endpoints from hooks.py + schemas
- Deployed updated playbooks (PM + worker) to projects 1 and 7
- Cleaned stale register/deregister references from PM project rules

### Sprint 49 — Stale Ticket Detection + SubagentStop Fix
- Stale ticket detection: frontend fires `POST /api/tickets/stale-check` at 10-min intervals, backend creates deduped alerts
- SubagentStop hook fix: 4 field mismatches (agent_type, agent_id, agent_transcript_path, hook_event_name) causing silent token loss. New `_handle_subagent_stop()` creates separate sessions keyed on agent_id, no longer prematurely closes TL session
- `playbooks_deployed_at` field on Project model + "last deployed" timestamp on frontend
- TL playbook: alert triage at natural cadence points
- PM playbook: stale ticket handling procedures
- CSS: sidebar logo height aligned with header (48px)

### Sprint 50 — Alert UX Overhaul
- `POST /api/alerts/send-to-team` — writes open alerts to `.claude/ALERTS_PENDING.md`, tags with `user_sent_at`
- Auto-unlink: ALERTS_PENDING.md auto-deletes when last open alert resolves
- "Send alerts to team" button on ProjectPage next to dismiss-all
- Dashboard alerts redesigned as read-only table (actions on ProjectPage only)
- TL playbook + agent def: ALERTS_PENDING.md priority check

### Sprint 51 — Doc Overhaul
- README.md: 591 → 230 lines. Removed dead content, added new features, lean API reference
- ARCHITECTURE.md: 776 → 583 lines. Fixed wrong hook_sessions columns, removed dead endpoints/scripts, added SubagentStop field mapping, stale detection, ALERTS_PENDING lifecycle
- CLAUDE.md: endpoint count 83 → 93

### Investigation: Alert delivery gap
- Identified that alerts are "write with no reader" — agents create them but no programmatic path to notify the TL
- Explored options: playbook polling, mandatory PM loop, SendMessage on alert creation
- Landed on: TL playbook cadence points (check at natural breakpoints) + ALERTS_PENDING.md file as manual human trigger
- Fundamental constraint: Claude Code Teams has no way to externally interrupt an agent mid-session
