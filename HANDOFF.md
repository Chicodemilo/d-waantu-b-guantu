# Handoff — D'Waantu B'Guantu

> Session-to-session continuity notes. Read this at the start of every session. Update it at the end.

## Current State

Sprint 51 completed. 4 sprints this session (48-51). 426 backend tests passing. README and ARCHITECTURE fully overhauled. Team is up and idle (Archie, Pam, Barry, Freddie).

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

1. **Token efficiency** — investigate ways to lighten token usage when using the DWB system. Agents burn context reading playbooks, API calls, status checks. Find ways to reduce overhead without losing capability.
2. **Test SubagentStop fix live** — the field mismatch fix (DWB-261) was committed but hasn't been validated with a real CI team session yet. Run a team and verify teammate hook sessions appear in the DB with correct tokens.
3. **Update HANDOFF.md at CI project** — the CI project's HANDOFF may reference register/deregister endpoints that no longer exist.

## Last Session (2026-04-17)

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
