# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (end of 2026-08-12, DWB session 1 of the new DB era)

- Working tree committed + pushed to origin/master through `0b30979`. Backend 1544 passing, frontend 266 passing.
- NOTE: this DB was seeded fresh (seed_personal_dwb) — ticket numbering restarted at DWB-001; git history's DWB-49x/50x keys predate the reset (human confirmed: don't care about collision risk). Current sequence is at DWB-033; sprint-close automation mints tickets too (024/032 were auto), so always check max ticket_number before creating.
- Sprints this run, both closed: **S23 "Standards Auditor Phase 1"** (9 done) + **S24 "Auditor Phase 2 + tracking debt"** (7 done). Epic 10 (Standards Auditor). **Sprint 25 (id 25) is PLANNED, not active** — 10 backlog tickets: DWB-024 (rescoped: Sage black-box audit-system verification), 020 (score-broadcast severity bug), 025 (Docs page missing CODING_STANDARDS.md), 030 (runner type hints), 001/002/003 (aggregator/precision/dedup debt), 019 (deferred S1 tests), 032 (auto S3 test ticket, Sage).
- **Team NOT shut down but CC teams don't survive sessions** — all teammates (Pam_DWB ag12, Barry_DWB ag13, Freddie ag14 [ran as Freddie_DWB-2 teammate name], Sylvie_DWB ag15, Dolores_DWB ag17) are dead processes next session. RESPAWN per playbook: spawn-prepare + pending marker + Agent tool. All wrote session-complete memory blocks.
- DWB session 1 closed (6.23M tokens rolled up). The_Auditor = agent 51 (system agent, role auditor, seeded by migration dwb028).

## Shipped this run: the Standards Auditor system (end-to-end, self-enforcing)

- **Global law**: `docs/rules/global/coding-standards.md` (instruction id 9) — THE cross-project sheet. Deploys with the playbook bundle everywhere: `.claude/rules/global/` mirror + repo-root `CODING_STANDARDS.md` built from it (global body + preserved `## Project Extensions`; marker-based refresh; markerless human files untouched+logged; non-Jira banner). DWB's own root doc converted to this format. Edit the sheet → sync (`sync_instructions.py --import`) → deploy propagates.
- **Auditor**: `scripts/run_standards_audit.sh` / `standards_audit.py` — spawns a FRESH headless `claude -p` from a tempdir (provably context-starved), prompt = sheet + project extensions (DWB-029) + facts-only attribution block (DWB-023, names scorecards to real roster agents w/ fail-loud guard) + diff + strict-JSON contract. Config from `.env` (`STANDARDS_AUDIT_MODEL` required, `STANDARDS_AUDIT_AGENT_ID` optional → falls back to The_Auditor by name).
- **Storage/API**: `standards_audit` table + `/api/standards-audits` (verdict pass/reject, violations[], scorecard[], MEDIUMTEXT details) + explicit idempotent `/{id}/apply-scorecard` → score_event ledger (source=audit, audit_grant/audit_demerit; bypasses peer caps by design).
- **Visibility (DWB-028)**: every audit POST raises an alert (info=pass, warning=reject) + activity-feed attribution to The_Auditor. **Audits page** `/projects/:id/audits` (DWB-031): summary stats (pass/fail %), expandable rows (ref/date/verdict → who/violations/scorecard). ProjectPage section (DWB-018). Shared render pieces promoted to `components/common/` (AuditVerdictBadge/AuditViolations/AuditScorecard).
- **Gate**: `force_standards_audit` (DWB-017) — sprint close requires a PASSING audit in-window. ON for project 5. `force_coding_standards_md` ON for all 5 projects (doc-exists gate; complements, both kept).
- **Token attribution FIXED (DWB-022)**: root cause was `increment_tokens` (ticket token-report endpoint) writing tokens with no tracking_log event + token_source left 'unknown' — NOT SubagentStop. Now atomic (ledger event + cache in one commit), attributed (X-Agent-ID else assignee, 400 if neither), real token_source. Migration dwb022 reconciled 10 orphan tickets (~550k phantoms → source='reconciled'). Rollups now PARTIALLY TRUSTWORTHY: reconciled history + correct future. Case B (Sylvie/Dolores 0-token closes) = unmeasurable, documented, not fixable retroactively.
- **Overhead doctrine (DWB-033, system-wide via playbooks)**: PM stands down on serial stretches (<3 active workers); workers get ticket queues not spawn-per-ticket; PM lane-shards tickets file-disjoint; migrations single-holder per sprint. Piloting worktree-twins for same-lane parallelism = future work, not yet doctrine.

## The cadence (now proven, keep it)
Worker builds → in_review → TL reviews → stage → `run_standards_audit.sh --staged --ticket-id N --sprint-id M` → REJECT: findings back to worker (or TL for trivia); false positives ADJUDICATED on the record (uphold / waive-with-law-amendment / overrule) → PASS → TL commits/pushes → done → carrots/sticks. 20 audits recorded; every reject remediated same-day. Law precision improved 5x through adjudication (Commits scope, Headers scope, fixture-identifier carve-out, hooks-are-services-for-React, Backend-shape-governs-app/, services-exception reality amendment).

## Gotchas (carry forward)
- **Teammate permission dialogs freeze workers invisibly** — silent worker + no tree/ticket movement = check the human's agent panel FIRST, respawn LAST (memory: stalled-teammate-check-permission-dialog). Respawn-over-frozen-pane: new teammate gets -2 name suffix, same agent_id (marker is id-aware); brief replacements to VERIFY-not-clobber partial work; stand down the original immediately.
- **One-off DB scripts must run from backend/** (cwd-relative .env resolution; from repo root you get connection-refused on 3306).
- **Session-close headline may be overridden by the synthesizer** even on ai_confident close with a supplied headline (observed on session 1 close; playbook says supplied wins — possible DWB-500 regression, worth a ticket).
- Score/carrot broadcasts land at CRITICAL severity → alert-board noise (bug ticket DWB-020, backlog). PM triage: audit alerts = signal, broadcast carrots = ack-and-move-on.
- Ticket ids ≠ ticket keys; demo project occupies ids 126-155. Use ids in API paths.
- Auditor runs cost ~1 claude -p call (~30-90s); batch small diffs into one audit where sensible; audits 2-20 exist — the trail is real history, don't delete.
- Message timing crosses constantly (Pam's snapshots often stale vs TL actions); verify before concluding a teammate missed something.

## Housekeeping
- Uvicorn + Vite dev servers were left RUNNING (ports 8000/5173); MySQL container up. Docker disk-high warning (35GB) persists — infra, unactioned.
- `.env` has STANDARDS_AUDIT_MODEL set locally (deliberately not committed).
