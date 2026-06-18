# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-17 close)

- **Sprint S66 (id=107) active**, epic 21 in_progress.
- **Last DWB session: id=26**, opened 2026-06-17 18:41 (regex), closed 20:02 (regex/explicit on user "shut it down"). ~936k tokens, ~80 min. Headline set manually (regex closes carry none).
- **Team `session-26822b38` down:** Pam_DWB (14) + Barry_DWB (21) posted session-complete and were sent shutdown after their work. Respawn next session via Agent/TeamCreate + spawn-prepare + pending marker; do NOT SendMessage these names cold.
- **Working tree dirty, UNCOMMITTED** (carried from prior sessions + today). Untracked `backend/dwb.db` is a stray SQLite artifact — investigate before any commit, do not commit it blindly.

## Shipped today (S66)

| Ticket | Status | One-line |
|---|---|---|
| DWB-394 | done | Close-matcher negative-context guard: CLOSE `<name>` stop-word exclusion + interrogative/reported-speech skip. Questions/quotes no longer false-close; real commands still do. |
| DWB-395 | done | `POST /api/sessions/{id}/reopen` (replaces manual DB null-out) + 120s grace-window resurrect for regex/ai_classifier closes only. |

Both reviewed (diffs read, suite run, behavior live-verified) and accepted. Backend **1150 passing** (was 1113). Server restarted with `--reload` so fixes are live.

## Open backlog

- **DWB-396 (TO FILE):** Layer-1b transcript scan still false-closes on close phrases that appear as *example text / agent prose* in a transcript (today: my own brief's "shut it down for the night" closed session 26 mid-work). Fix: scope the transcript close-scan to user-authored turns only. DWB-394 covers questions/reported-speech, NOT example prose.
- **DWB-397 (TO FILE):** Session-close compaction gate is mis-scoped. It blocks `ai_confident` close on (a) user-authored governance docs (`team_lead_playbook` 7592/4000, `pm_playbook`, `project_rules_worker`) and (b) offline non-participant agents' memory (Dolores/Freddie/Sylvie). Narrow it to session participants (à la DWB-326), exempt deployed user-authored docs, and/or raise the playbook ceiling (4000 too low for the TL playbook).
- **Uncommitted tree** + `backend/dwb.db` investigation (above) if user asks to commit.

## Next session

- **Agent point system** (user-chosen next feature): stars/rank/demerits synthesized from existing signals (failure_records, rework, token efficiency, gate compliance). Draft epic/tickets for review first — design approved, build NOT yet authorized. Self-contained, no cross-repo. (Inter-project Archie comms deferred — bigger architecture lift, collides with agnostic-repo model.)

## Gotchas (carry forward)

- **`.claude/` Edit by subagent = crash.** Only the TL edits `.claude/` files directly.
- **Close regex fires on substrings.** Genuine commands close correctly; DWB-394 guards questions/reported-speech; example prose in transcripts still slips through (DWB-396).
- **Regex/idle/slash closes carry no headline** — stamp manually if the dashboard summary matters.
- **No reopen via API was the old pain — now `POST /api/sessions/{id}/reopen` exists** (409 if another session open).
- **Compaction gate has no override path** and over-scopes (DWB-397). `/dwb-close` (slash) is gate-exempt if you need to close past it.
- **Doc ceilings:** HANDOFF 1500, ARCHITECTURE 7500, README 3500, playbook 4000 (`app/config/token_budget.py`). README + ARCHITECTURE trimmed under ceiling today.
- **`GET /api/alerts?status=open` is NOT project-scoped** — pass `project_id` or you'll see other projects' alerts.
- **`SendMessage` is name-literal**; verify suffix on respawned teammates. After compaction, `ls ~/.claude/teams/<team>/inboxes/` first.
- **DWB tracks 9 projects**; only project 1 is DWB itself.
