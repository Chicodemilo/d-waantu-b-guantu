# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-23, end of day)

- Working tree clean; all work committed AND pushed to origin/master (tip `c9fa301`). Backend 1350 passing, frontend 185 passing.
- Epic 33 "Archie Channel" / sprint S69 (id=123) DONE: DWB-436..444 + DWB-439 all closed and accepted. No open tickets, no open alerts.
- DWB session 40 closed. Team stood down (Barry, Freddie) - respawn before use, verify `presumed_live`, do NOT SendMessage cold names.
- Backlog: **DWB-445** (parked, not filed) - dormant-wake spike: write into CC's live-watched teammate-inbox to poke a stone-cold-idle session. Also carried: DWB-413 (delete_project 500 - largely mitigated by the channel cleanup), DWB-396 (prose-false-close).

## Shipped this session (Archie Channel, epic 33)

Cross-project team-lead messaging. Archies (team-leads, one per project) send DIRECT (to one archie) or BROADCAST (to all) messages; every archie sees the whole channel.
- Tables `tl_messages` + `tl_message_reads` (NOT project-scoped; composite-PK read receipts, CASCADE on message delete). `from_project_id` NOT NULL; delete_project clears the project's sent messages (DWB-436).
- API `/api/tl-channel` (DWB-437): send (direct/broadcast), list (cross-project, per-viewer read-state), unread?agent_id=, mark-read. Role-guarded to team-leads (400 otherwise). One alert ping per recipient (direct=target; broadcast=every other active TL). `read_by` = full reader roster `[{agent_id, agent_name, read_at}]` (the UI Read column shows ALL readers, not a count).
- Surfacing at spawn (DWB-438): `agent_memory.scaffold_agent_dir` renders an unread block in `identity.md` for team-leads only, beside the scoring standing block, then marks those msgs read.
- Surfacing on every turn (DWB-443/444): a `channel-poke` Stop hook (`/api/hooks/channel-poke`) returns a `{"decision":"block",...}` so a LIVE session self-surfaces unread on its NEXT turn boundary - no human relay. Wired into `_HOOKS_SETTINGS_BLOCK` + `.claude/settings.json`, redeployed to CI.
- `/tl` slash command (DWB-439): `/tl @Archie_X msg` (direct) or `/tl msg` (broadcast). Body kept verbatim.
- Archie Channel dashboard page + read-state column (DWB-440). Docs in ARCHITECTURE + README (DWB-441).
- Scoring tweak (DWB-442): a HUMAN carrot (source=human, delta>0) makes the peer alert a pile-on CTA ("Pile on: /carrot <name>"); human sticks + all peer events stay notify-only.

## Gotchas (carry forward)

- **Poke needs a turn boundary.** The Stop hook fires every turn an agent completes, so a live/working session self-surfaces unread within one turn. A stone-cold-idle session (already Stopped, no activity) won't wake until it next acts - that's the DWB-445 spike.
- **settings.json hot-reload caveat.** A redeploy writes the poke hook into a repo's `.claude/settings.json`, but CC likely loads hooks at session start - an already-running session may need a restart to activate the new hook (439's identity.md surfacing still catches unread at next spawn).
- **`_HOOKS_SETTINGS_BLOCK`** (`routers/playbooks.py`) is the canonical hook config `deploy-playbooks` writes into `settings.json`; drift-guard test (`test_playbooks.py`) asserts it equals DWB's own `.claude/settings.json` hooks. Keep them in exact sync or the test fails / a deploy clobbers hooks.
- **`.claude/` Edit by subagent = crash**; only the TL edits `.claude/` (commands, settings, playbooks). Workers' memory goes through the API.
- **No modal component** in the frontend - inline text confirms only (firm rule). No icons, no em-dashes.
- **Ticket key != db id** - PATCH by db id (e.g. DWB-437 = id 995).
- **Doc ceilings** (`token_budget.py`): HANDOFF 1500, ARCHITECTURE 7500, README 3500. ARCHITECTURE/README are near ceiling - condense to offset additions.
- Dev server (vite :5173) needs a restart / hard-refresh to pick up new frontend files.
