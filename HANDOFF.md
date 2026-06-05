# Handoff — D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State

**No active sprint.** S64 closed 2026-06-05. Working tree clean, commit `64f5d84` pushed to `origin/master`.

623 backend tests passing + 13 playbook + 25 D2J = 661 across all suites.

## Active Decisions

- **Passive hook-based token tracking** via `.claude/settings.json` hooks (SessionStart/End/SubagentStop).
- **Marker format = JSON dict** at `.claude/agents/active/<session_id>`. TL pre-writes `pending-<agent_id>-<unix_ms>-<rand4hex>`; resolver renames on first SubagentStop (DWB-304).
- **System-wide unique agent names** (DWB-315): `UNIQUE(name)`. Fixed roles use `_<PREFIX>` suffix.
- **DB-authoritative roster** (DWB-312): no TEAM.md. `GET /api/projects/{id}/team`.
- **No PM for small teams** (≤2 workers).
- **TL writes `.claude/` files on workers' behalf** (subagent + `.claude/` write crashes CC).
- **Pam Jira limits** (DWB-323/324): PM can never `dwb2jira sprint close/create/edit/delete`. CLI refuses exit 1.
- **Consolidation gate has TEETH** (DWB-328): ack endpoint returns 400 if owned files over ceiling without per-file override. **Refusal is the signal to TRIM, not idle.**
- **Participants for sprint** (DWB-326): required-ack set = agents with ticket / comment / tracking_log / hook_session / activity_log in sprint window.
- **deploy-playbooks now ships agent defs** to target `.claude/agents/` (skips same-path on DWB self-deploy).
- **User-authored docs are read-only** (agent defs, playbooks, project_rules, root docs) — no edits without explicit naming or ticket scope.

## Gotchas

- Alembic autogenerate misses MySQL enum changes — write manual migrations.
- SubagentStop's `agent_transcript_path` points at a synthetic path; fallback scans parent session's projects-dir `.jsonl` filtered by `agentName` (DWB-311).
- `agent_type` in SubagentStop payload is empty string in practice.
- Stale `.pyc` cache can mask real test failures — `find backend -name __pycache__ -exec rm -rf {} +` before reporting.
- `participants_for_sprint` counts TL admin acks (DWB-329 backlog to refine).

## Backlog

- **DWB-316** — Dashboard viewer for CC Teams inbox files
- **DWB-329** — Refine participants_for_sprint to exclude admin acks
- **DWB-331** (not yet filed) — Agent defs become thin stubs (cross-ref to playbooks)
- Active consolidation work — system drives the trim, not just demands it (architectural follow-up)
- `compute_token_budget` layering inversion (lives in routers, consumed by services)
- `agent_consolidation_acks.overrides` nullable check constraint

## Last 4 Sprints

**S64 — Gate enforcement smoke-test (closed 2026-06-05).** 1 ticket (DWB-330). Inflated HANDOFF + Barry's scratchpad over ceiling, sprint close attempted, gate refused both acks with proper violations payload, trim → retry → 201 clean. The test of the test passed. The lesson the test exposed (refusal ≠ done; trim is the work) is now baked into all 6 docs.

**S63 — Gate teeth + ceiling rebalance (closed 2026-06-05).** 4 tickets. DWB-326 participant scoping, DWB-327 ceiling rebalance + trims, DWB-328 ack endpoint refuses over-ceiling without per-file override, DWB-325 carry from S62. Edge case caught: DWB-329 backlog.

**S62 — Force_team_md retire + Pam safety guards (closed 2026-06-05).** 5 tickets. force_team_md fully ripped (column dropped, frontend panel deleted, 13 tests deleted, doc cleanup), consolidation gate audited + canary, Pam safety rules in 4 files, D2J CLI guard with 25 new tests, consolidation gate documented across 6 files.

**S61 — Doc audit + sync (closed 2026-06-05).** 4 tickets. 38 stale items across 13 files synced to S59+S60 reality.

## Session-end notes (2026-06-05)

- Committed and pushed everything: `64f5d84 Sprints 58-64: identity, live attribution, gate teeth, doc sync` — 118 files.
- `.gitignore` extended for `.claude/agents/active/`, `.claude/agents/memory/`, `.claude/scheduled_tasks.lock`, `ALERTS_PENDING.md`.
- deploy-playbooks now ships agent defs alongside playbooks. Same-path guard prevents self-clobber on DWB.
- Team currently stood down: Barry-2, Dolores-2 in dwb-s60-attribution config but idle.
