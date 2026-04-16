# Handoff — D'Waantu B'Guantu

> Session-to-session continuity notes. Read this at the start of every session. Update it at the end.

## Current State

Sprint 47 completed. Team Status panel redesigned. LiveSessions being rewritten to be ticket-status driven (in progress when session ended). 426 backend tests passing. Team is up and idle.

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
- **Team Status panel is ticket-status driven** — agent shows "working" if they have an in_progress ticket. No hooks, no manual registration. Deterministic.
- **TL orchestrates only** — never writes code, edits files, or makes direct fixes. Delegates everything to workers, reviews their output.
- **Playbooks vs project rules**: playbooks are generic (overwritten on deploy), project rules are project-specific (never overwritten). 6 files total per project.
- **DWB is private** — never mention DWB in Jira, PRs, commits, or external content. Generalized for all human users, not just Miles.

## Gotchas

- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for enum ALTER
- Frontend vitest has 23 pre-existing mock failures (`response.text is not a function`) — not blocking
- `deploy-playbooks` pushes TL, PM, and worker playbooks from `docs/` + creates blank project rules files
- Demo seed creates fake repo at `/tmp/dwb-demo-project` — must include all gated doc files
- Deploy is destructive on playbooks — always re-deploy after committing changes to `docs/`
- `tickets.find()` returns first match — sort by updated_at desc when picking in_progress tickets
- Hook sessions exist for the main session (TL) but teammates don't trigger SessionStart hooks — that's why we moved to ticket-status-driven Team Status

## Known Bugs

### LiveSessions rewrite in progress
Pixel is rewriting LiveSessions.jsx to be ticket-status driven (no hook session dependency). Should be committed shortly after this session.

## What Needs Doing Next

1. **Review and commit LiveSessions rewrite** — Pixel should have it done
2. **Review and commit project rules files** — team is populating them
3. **Review and commit PM playbook updates** — Devin added "Ticket Status Drives the Dashboard" section
4. **Fix wrong ticket bug** — LiveSessions should sort in_progress tickets by updated_at desc before picking
5. **Deploy updated playbooks to CI** — after committing the PM playbook changes
6. **Consider removing register/deregister-agent endpoints** — they're now unnecessary since Team Status is ticket-driven

## Last Session (2026-04-16)

### Sprint 45 — Hardening & Cleanup
- FK cascade on ticket child tables (7 tables)
- `cancelled` value added to TicketStatus enum
- `datetime.utcnow()` deprecation fix
- TL + PM playbooks updated for passive hook tracking

### Sprint 46 — Team Manifest & Worker Playbook
- TEAM.md (roster only), HANDOFF.md (continuity), force_team_md + force_handoff_md gates
- worker.md general playbook, TEAM.md.template
- "Agents" renamed to "Team" in nav
- Playbook restructure: docs/ = deployable, .claude/agents/ = local

### Sprint 47 — Team Page: Playbook Inspector & Deploy
- Deploy button moved to Team page
- PlaybookInspector with split Playbooks/Project Rules sections + tooltips
- Path + last_modified metadata on all panels
- Backend: playbook-files endpoint, last_modified on docs endpoint
- Register/deregister-agent endpoints (may be deprecated now)

### Post-sprint work
- Tools section overhaul (section headers, one button per row, individual tooltips)
- Team Status redesign (roster-based, not hook-session-based)
- Decision: Team Status is ticket-status driven (deterministic, no hooks/registration)
- PM playbook updated: "Ticket Status Drives the Dashboard"
- agent_rules link removed from sidebar
- TL orchestration rule reinforced — TL never codes, always delegates
- Project rules files: blank templates created on deploy, team populating them
