# Handoff — D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

---

## Note from Archie_CI — 2026-06-08T19:25:00+00:00

User-side bug report from FRAUDI (CI project_id=5). `PATCH /api/tickets/{id}` with body `{"sprint_id": null}` returns generic 500 (no detail). Status-only PATCHes work fine (e.g. `{"status": "backlog"}` → 200). Only the null on sprint_id blows up. OpenAPI schema says the field accepts `int | null`, so this looks like a server-side handler bug, not a validation reject.

Impact: I cannot fully detach tickets from a closed sprint. Workaround is leaving `sprint_id` pinned to the old sprint while flagging status=backlog, then the next sprint's PATCH overwrites with a real int.

Apologies for popping into your HANDOFF — Miles asked me to drop the note here so it does not get lost. No action expected from me; flagged for whenever the DWB-side team picks it up.

— Archie_CI

---

## Current State

**Sprint S66 active.** Epic 21 (`Fixing time and token tracking`) is the only in_progress epic. S66 (`Passive Session-Based Tracking + Single-Active`) opened 2026-06-08 with 2 tickets filed, more to draft. Team stood down; nothing spawned.

**Uncommitted changes** in working tree (frontend + 3 playbooks). User has not authorized commit. Decide on resume.

623+ backend tests still passing from last verified run on master (`64f5d84`). New session work has not been re-run.

## Tickets in S66

- **DWB-331** (id 808, Barry_DWB, todo) — Enforce single in_progress epic + single active sprint per project. Validators in epic/sprint routers (409), DB-level constraint (MySQL has no partial unique; worker picks generated-column + composite unique vs. trigger).
- **DWB-332** (id 809, Barry_DWB, todo) — Non-Jira project: agent-facing visibility + hard gates. Identify-flow exposes `jira_enabled`, deploy-playbooks scrubs Jira content on non-Jira targets, ticket router refuses `jira_issue_key` writes when `jira_base_url` is null.

**Not yet drafted (main S66 thrust):**
- DWB session model + schema design
- Session-open detection (TL SessionStart hook)
- Session-close detection (TL SessionEnd hook vs. user exit phrase vs. idle timeout)
- Time + token rollup by DWB session
- User-facing session lifecycle docs (how to open/close: "you are archie, read playbook" / "have the team write docs and exit")

## Active Decisions

- **Passive tracking requirements (S66 driver).** Fully passive: agents have zero knowledge of tracking. Tracks BOTH time and tokens. Bounded by DWB session (user open/close phrases), not Claude Code session. A DWB session can span multiple Claude Code sessions (TL + spawned workers). See `~/.claude/projects/-Users-mchick-Dev-d-waantu-b-guantu/memory/project_passive_tracking_requirements.md`.
- **Single in_progress epic, single active sprint per project** is now policy (DWB-331 enforces). Pre-existing dupes cleared before opening S66 (epics 6, 7, 10 closed; S65 closed via TL admin acks).
- **No icons, no em dashes** anywhere — UI, docs, commits, prose. Documented in `docs/worker_playbook.md` Style Rules.
- **Inline text confirmations** (trigger swaps to "confirm? yes / cancel") over modals. No modal component exists; do not build one. Reference: `EpicList.jsx` mark-as-closed, `ProjectPage.jsx` delete/disable.
- **Skip ceremony for trivial fixes** is USER-triggered, not TL-decided. TL only edits directly when user signals it ("just do it", "fast doer", etc.) AND change is under ~20 lines, 1-2 files, unambiguous. See `docs/team_lead_playbook.md` § 4c.
- **Side-ticket lane** in sprints: 1-3 small polish tickets (CSS/UI) can ride along the main goal. Soft rule. § 4d in TL playbook, mirrored in PM playbook.
- **Slate-blue gradient** `#3a4a7c` (dark) -> `#a8b5d1` (light) is the established DWB chart fill. Applied to SprintVelocity bars (per-bar gradient via `background-clip: text` on the filled stack), AsciiProgressBar fills, and a new `.ascii-chart__bar--gradient` variant used by `TokenOverview` "Tokens by Project".

## Gotchas

- Alembic autogenerate misses MySQL enum changes — write manual migrations.
- SubagentStop's `agent_transcript_path` points at a synthetic path; fallback scans parent session's projects-dir `.jsonl` filtered by `agentName` (DWB-311).
- `agent_type` in SubagentStop payload is empty string in practice.
- Stale `.pyc` cache can mask real test failures — `find backend -name __pycache__ -exec rm -rf {} +` before reporting.
- `participants_for_sprint` counts TL admin acks (DWB-329 backlog to refine).
- S65 close path required 5 TL admin acks because team was stood down. This is allowed per playbook but noisy; DWB-329 fix should help.

## UI Changes (uncommitted, on master working tree)

- `ProjectPage.jsx`: section reorder. Header > Tools (pulled up 20px) > Alerts > Current Sprint + Activity > Time & Tokens > TokenBudget > Velocity > Epics > Team Status (demoted) > Tickets link.
- `ConsolidationStatus.jsx`: not rendered. Commented out in ProjectPage with date + rethink note. Component file untouched; can revive.
- `SprintVelocity.jsx`: smooth slate-blue gradient on filled portion via `background-clip: text`. Labels alternate `--green` / `--green-bright`, bold, 10.35px, 4px gap. Sort still newest-first.
- `AsciiProgressBar` / `.progress-bar__filled`: gradient.
- `AsciiChart`: new `--gradient` color variant. `TokenOverview` "Tokens by Project" uses it. Failures-by-Type stays orange (semantic).
- `AlertBanner.jsx`: single-line meta row (`time :: source :: body...` with ellipsis on overflow), title on second line in severity color. Container max-height 200, per-banner padding tightened.
- `EpicList.jsx`: on `status=open` epics, inline "mark as closed" link below the badge. Confirm flow swaps to "confirm? yes / cancel" (cancel in `--orange`).
- Icons + em dashes removed wherever touched.

## Playbook Changes (uncommitted)

- `docs/worker_playbook.md` § Style Rules: added no-icons, no-em-dashes, inline-text-confirms (universal).
- `docs/team_lead_playbook.md` § 4c (Skip Ceremony) + § 4d (Side-Ticket Lane).
- `docs/pm_playbook.md` § 1: side-ticket-lane awareness paragraph.
- `.claude/project_rules_*.md` intentionally not touched — user requested playbooks only.
- Deploy with `POST /api/projects/:id/deploy-playbooks` on resume so linked projects pick up the standing rules.

## Backlog

- **DWB-316** — Dashboard viewer for CC Teams inbox files
- **DWB-329** — Refine `participants_for_sprint` to exclude TL admin acks
- **DWB-331** filed, awaiting work
- **DWB-332** filed, awaiting work
- Main S66 thrust tickets (passive session model, open/close detection, rollup, lifecycle docs) — to draft
- Consolidation gate panel: rethink whether to revive, scope to sprint-close-only, or remove
- `compute_token_budget` layering inversion (lives in routers, consumed by services)
- `agent_consolidation_acks.overrides` nullable check constraint
- D2J-side CLI gate (refuse-to-operate on non-Jira-configured project) — cross-repo follow-up from DWB-332

## Last 4 Sprints

**S66 (active 2026-06-08).** Passive session-based tracking. 2 tickets filed (DWB-331 single-active enforcement, DWB-332 non-Jira hard gates). Main-thrust tickets still to draft.

**S65 — Token + time tracking gap audit (closed 2026-06-08).** Closed via TL admin acks for all 5 participants (team stood down).

**S64 — Gate enforcement smoke-test (closed 2026-06-05).** 1 ticket (DWB-330). Inflated HANDOFF + Barry's scratchpad over ceiling, sprint close attempted, gate refused both acks with proper violations payload, trim -> retry -> 201 clean. The test of the test passed.

**S63 — Gate teeth + ceiling rebalance (closed 2026-06-05).** 4 tickets. DWB-326 participant scoping, DWB-327 ceiling rebalance + trims, DWB-328 ack endpoint refuses over-ceiling without per-file override, DWB-325 carry from S62.

## Session-end notes (2026-06-08)

- Session opened with "you are archie, you are team lead, read the playbook" — proved out as the open phrase for the future session lifecycle work.
- Closed all stale in_progress epics (6, 7, 10) and active sprint S65 to land at single-active state before opening S66.
- Two side cleanup items handled directly (consolidation panel hide, mark-as-closed link) under user-triggered ceremony-skip rule.
- New memory entries added: no-icons-no-em-dashes, skip-ticket-overhead (revised to user-triggered), side-ticket-lane, don't-relitigate-sprint-placement, inline-text-confirms, passive-tracking-requirements.
- Uncommitted: 11 files (8 frontend, 3 playbooks). User has not authorized commit. Decide on resume.
- No team spawn this session. Team stays stood down.
