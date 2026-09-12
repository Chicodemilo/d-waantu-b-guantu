# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (end of 2026-07-28, DWB session 69)

- **Repo is on branch `fix/session-close-overflow-dwb505-506`** (tree clean, pushed). PR #3 open against master with all of this session's code; Miles merges. After merge, next session should checkout master + pull.
- S77 (Session Tracking Reliability, epic 48) closed: DWB-505 + DWB-506 both done, backend 1501 passing (posted as test run 187). Stale S76 + epics 33/40-era leftovers were closed at startup; epic 48 completed.
- DWB session 69 closed explicit (1.27M tokens, 3h39m - honest post-fix numbers).
- **Team shut down**: Barry_DWB wrapped (session-complete posted) and was sent shutdown after both tickets accepted. RESPAWN before use next session: spawn-prepare + pending marker + Agent tool; verify live names; never SendMessage cold roster names.

## Shipped this session (all settled, in PR #3)

- **DWB-505**: `dwb_sessions.total_tokens` INT overflow (5.47B rollup) 500'd every close of CI session 65 for 12 days. BIGINT migration `dwb505a1b2c3` (dwb_sessions/hook_sessions total_tokens, tracking_log.tokens); close_session clamps + warns instead of aborting; idle sweeper closes now savepoint-isolated (one failing close was rolling back the ENTIRE sweep batch every cycle - that was the "sweeper dead since 7-17" mystery). Session 65 closed live, verified from CI side.
- **DWB-506**: token totals summed `cache_read_input_tokens` every turn (re-counting the whole cached context; ~33x inflation ALL projects). Totals now = input+output+cache_creation. Miles-approved Tier A recompute EXECUTED across all 5 layers from stored token_breakdown JSON: 10.58B -> 320M canonical (session 65: 159.4M). Verified zero diff vs breakdowns, DWB-305 invariant 0 on all projects. **Rollback snapshots in `dwb506_bak_*` tables - drop once Miles is comfortable.**

## Open items (genuinely open)

- **Playbook 9-col ticket table** (Archie_CI request, Miles authored the change on CI): update `pm_playbook § Ticket Display Format` to `DWB # | Jira # | Type | DWB Sprint | Jira Epic | Jira Sprint | Title | Owner | Status`, redeploy. Proposed twice, NOT yet approved - don't file without a go.
- **create_test_result enum bug**: "Data truncated for column 'status'" recurring in error_logs since 7-21 (some project posts a bad status value). Unfiled side-lane candidate.
- Drop `dwb506_bak_*` snapshot tables after Miles signs off on corrected numbers.
- Old backlog unchanged: DWB-492 (ticket_key filter), DWB-502 (help portal fallback), DWB-503 (TF-IDF df perf), auto-created test tickets (DWB-504 = S76 tests, plus the S77 one). Check max ticket_number before filing new tickets.

## Gotchas (carry forward)

- **Token semantics changed 2026-07-28**: total_tokens = distinct work (input+output+cache_creation), cache_read excluded (still in breakdown). ALL history was recomputed, so cross-session comparisons are consistent - but any external notes quoting pre-fix numbers are ~33x inflated.
- Sprint close AUTO-CREATES the next test ticket and consumes the next ticket_number (ate DWB-504 this session). Reserve numbers after closing, not before.
- error_logs middleware only sees HTTP-path exceptions; background tasks (sweeper) log to the in-memory ring buffer (DWB-372) only. No error rows != healthy.
- uvicorn now runs WITH --reload (nohup, log at /tmp/dwb-uvicorn.log); it had run without --reload since 7-14, silently serving stale code. Check `ps aux | grep uvicorn` args when live behavior contradicts the diff.
- Message timing crosses constantly; teammate bodies often don't reach the TL - require key facts in the one-line summary.
- `.claude/` edits crash subagents; root `.md`, `docs/`, `frontend/src`, backend are safe.
