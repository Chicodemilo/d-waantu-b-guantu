# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-24, end of day)

- Working tree clean; all work committed AND pushed to origin/master (tip `74ee3e4`). Backend 1362 passing, frontend 188 passing.
- Epic 35 "Inter-Agent Comms Capture & Log" / sprint S70 (id=125) DONE: DWB-446..452 all closed and accepted.
- DWB session 42 closed. Team fully shut down (Barry_DWB-2, Freddie, Pam_DWB, Sage all terminated) - respawn before use, verify live name, do NOT SendMessage cold names.
- Backlog is clear. Prior carried items resolved this session: **DWB-413** (delete_project 500) verified DONE end-to-end (live DELETE 204 with full child rows); **DWB-396** (prose false-close) was never a real ticket - DWB-414 fully covers it; **DWB-445** (dormant-wake spike) DROPPED by user - not feasible in CC (a Stopped teammate's process has exited; no inbox watcher re-wakes it). Do not re-spike 445.

## Shipped this session (Inter-Agent Comms, epic 35)

Captures native Claude Code SendMessage traffic between agents into DWB, per project.
- `inter_agent_messages` table (DWB-446): project_id NOT NULL, dwb_session_id nullable (display only), from/to agent id+name, body TEXT, summary, created_at indexed. Migration `dwb446a1b2c3`. Added to `delete_project` cascade. New `capture_agent_comms` bool on projects (default ON).
- Capture endpoint `POST /api/hooks/agent-message` (DWB-447): resolves SENDER from session_id via the existing token-attribution resolver (`_resolve_tool_action_context`), recipient best-effort by name; `to_agent_name` always stored. NOOP (200, no insert) when toggle off. Bodies ARE stored (agent text, not user text - privacy rule N/A).
- List/clear (DWB-448): `GET`/`DELETE /api/projects/{id}/agent-messages` (paged, newest-first, envelope `{project_id,total,limit,offset,rows}`).
- 4-day purge (DWB-449): `purge_old_agent_messages` rides the idle sweeper, keys off `created_at` alone (survives sessions), logs counts. NOT tied to session close.
- SendMessage hook (DWB-450): `PostToolUse` matcher `SendMessage` -> remaps tool_input -> POSTs the capture endpoint. In `_HOOKS_SETTINGS_BLOCK` + `.claude/settings.json`, redeployed to CI/D2J/RVP.
- Frontend (DWB-451): project nav item "inter-agent comms" -> `/projects/:id/comms`. Dense terminal page, date-listed newest-first, body truncated single-line, inline-confirm Clear (no modal), polls 3s. Capture toggle in ProjectPage Tools panel.
- Tests + docs (DWB-452): 12 capture tests; ARCHITECTURE + README sections.

## Gotchas (carry forward)

- **`_HOOKS_SETTINGS_BLOCK`** (routers/playbooks.py) MUST stay byte-equal to `.claude/settings.json` hooks (drift-guard test). When a worker edits the block, the TL mirrors settings.json by GENERATING it from the dict (`.venv python -c "import _HOOKS_SETTINGS_BLOCK; dump into settings['hooks']"`), never hand-editing. See Archie memory.md.
- **`.claude/` Edit by subagent = crash**; only the TL edits `.claude/` (settings, commands, playbooks). Split .claude/-touching tickets: worker does backend half, TL does the .claude/ half.
- **ARCHITECTURE.md is at 7496/7500 - effectively AT ceiling.** Any addition MUST be offset by condensing first or the session/sprint close 422s. README 3496/3500 also tight.
- **`/carrot` `/stick` need args on ONE line** (`/stick Name 3 reason`); bare `/stick` just prints usage. Commands work (verified); portal carrot/stick UI hits the same endpoint.
- **settings.json hot-reload caveat**: already-running CC sessions on tracked repos won't fire the new SendMessage capture hook until restart; fresh sessions capture immediately.
- **No modal component** - inline text confirms only. No icons, no em-dashes.
- **Ticket key != db id** - PATCH by db id (DWB-446 = id 1007 ... DWB-452 = id 1013).
- **Comms page open design Q**: row shows `summary || body` truncated (body on hover). User to decide if it should always show body instead.
- Barry was respawned as **Barry_DWB-2** after a spawn-time stall (cosmetic; db id 21 intact).
