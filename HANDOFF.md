# Handoff — D'Waantu B'Guantu

> Session-to-session continuity notes. Read this at the start of every session. Update it at the end.

## Current State

Sprint 46 completed — Team Manifest & Worker Playbook. force_team_md and force_handoff_md gates added. All gates passing. 426 backend tests passing.

## Active Decisions

- Passive hook-based token tracking (Sprint 43) — no manual token reporting
- Plain CSS only, terminal aesthetic
- PM is mandatory on every team
- Teams stay alive until user says to shut down
- MySQL DB name stays `local_agent_tracker` (legacy, not changing)
- `.claude/agents/` = local Claude Code agent defs for this repo
- `docs/` = deployable playbooks pushed to other projects via deploy-playbooks
- TEAM.md = live roster (dynamic, grows as team spins up)
- HANDOFF.md = session continuity (this file)

## Gotchas

- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for enum ALTER
- Frontend vitest has 23 pre-existing mock failures (`response.text is not a function`) — not blocking
- `deploy-playbooks` endpoint pushes TL, PM, and worker playbooks from `docs/` to other project repos
- Demo seed creates fake repo at `/tmp/dwb-demo-project` — must include all gated doc files

## Known Bugs

### DELETE /api/tickets/{id} — FIXED (Sprint 45)
Was returning 500 due to missing FK cascade. Fixed with `ondelete=CASCADE` on all 7 child FKs.

### TicketStatus enum — FIXED (Sprint 45)
Added `cancelled` value. Tickets can now be closed as not-delivered.

## Last Session (2026-04-16)

### Sprint 45 — Hardening & Cleanup
- FK cascade on ticket child tables (7 tables)
- `cancelled` value added to TicketStatus enum
- `datetime.utcnow()` deprecation fix
- TL + PM playbooks updated for passive hook tracking
- TL playbook: "keep teams alive" rule added

### Sprint 46 — Team Manifest & Worker Playbook
- `worker.md` general playbook (all agents)
- `TEAM.md` template + DWB's own TEAM.md
- `force_team_md` gate (model, migration, gate-status, sprint close)
- Frontend: gate toggle + read-only TeamMdPanel on Team page
- "Agents" renamed to "Team" in nav/header

### Post-sprint cleanup
- Restructured playbooks: `docs/` = deployable, `.claude/agents/` = local agent defs
- Added `docs/worker_playbook.md` to deploy system
- Ticket proposal table format added to `docs/team_lead_playbook.md`
- Full docs roundup: ARCHITECTURE.md, README.md, QUICKSTART.md updated
- Header/comment audit across 26 files
- Split TEAM.md (roster only) from HANDOFF.md (continuity)
- Added `force_handoff_md` gate
