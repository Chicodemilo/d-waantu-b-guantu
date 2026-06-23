# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-23)

- Working tree clean; all work committed AND pushed to origin/master (tip `b6af775`). Backend 1317 passing, frontend 178 passing.
- Sprint S68 (id=118, epic 28 "Agent Scoring") active. All scoring tickets DWB-424..435 are done; no open scoring tickets. No open alerts on project 1.

## Shipped this session (two systems)

**Deterministic action capture (DWB-417..421):** PostToolUse / Notification / PreCompact hooks -> `/api/hooks/tool-use` + `/lifecycle-event` -> `tool_actions` table. Classifies file_written / message_sent (recipient only, no body) / agent_spawned / notification / context_compaction; emits activity-feed verbs. Fire-and-forget, always 200.

**Agent Scoring (epic 28, DWB-424..435):**
- `score_event` ledger (source of truth) + `agent_score` cache (rebuildable). `reputation` (all-time rank) + `influence` (per-sprint peer budget). Per-(agent, project).
- Auto-triggers in `scoring_triggers.py`: ticket close (+no-rework bonus), rework, test_failure, stale, zero_token_close, gate_miss, forgot.
- Human tools: `/carrot` `/stick` `/score` `/leaderboard` (`.claude/commands/`) -> `/scores/award` (free). Peer economy -> `/scores/peer` (X-Agent-ID), FLAT (any agent scores any other; only self-scoring barred); caps in `config/scoring.py`.
- Broadcast: human/peer carrot/stick notify all project agents via per-agent alerts (`alert.recipient_agent_id`); human = critical severity.
- Activity-feed events (DWB-432): `score_awarded`/`score_docked` (details: agent, signed delta, source, reason) + `lead_change` (new_leader/previous_leader). Auto-triggers NOT separately emitted.
- `identity.md` standing block (DWB-431): rendered each spawn in `agent_memory.scaffold_agent_dir` from `scoring.get_standing` - rank + tiered motivational line (best/podium/above/mid/below/dead_last/unscored).
- UI: leaderboard on Team Status (ProjectPage), Scoreboard tab on the team page (ProjectAgentsPage), carrot +10 / stick -10 buttons with inline reason (NO modal), AgentPage rank/tier + ledger, score on Roster + Dashboard.
- Cross-project guard (DWB-430): scoring writes require the subject (and peer actor) to be on the project. Docs (DWB-429): ARCHITECTURE + README. Full spec: `docs/agent_scoring_spec.md`.

## Team

Spawned this session: Barry_DWB (21, backend - built most of scoring), Freddie (19, frontend - ran as "Freddie-2" due to name collision with the parked instance), Pam_DWB (14, PM), Dolores (28, docs). **Stan (38, backend) CRASHED at spawn on DWB-432 and produced nothing** (last_seen null, ticket never moved); Barry recovered it. All parked at session end; respawn before use, verify `presumed_live`, do NOT SendMessage cold names.

## Gotchas (carry forward)

- **`_HOOKS_SETTINGS_BLOCK`** (`routers/playbooks.py`) is the canonical hook config `deploy-playbooks` writes into `settings.json`. It now includes PostToolUse/Notification/PreCompact - keep it in sync with `.claude/settings.json` or a deploy WIPES the capture hooks. Drift-guard test in `test_playbooks.py`.
- **Scoring is per-(agent, project)**; writes are membership-guarded. Slash commands live ONLY in DWB's `.claude/commands/` (deploy-playbooks does not copy commands to other repos).
- **`identity.md` standing**: `unscored` takes precedence over `dead_last` (new agents are encouraged, not threatened).
- **No modal component** in the frontend - inline text confirms only (firm rule).
- **`.claude/` Edit by subagent = crash**; only the TL edits `.claude/` (commands, settings, playbooks).
- **Ticket key != db id** - PATCH by db id (e.g. DWB-433 = id 979). Mixed these up once this session.
- **Doc ceilings** (`token_budget.py`): HANDOFF 1500, ARCHITECTURE 7500, README 3500.
- Dev server (vite :5173) needs a restart / hard-refresh to pick up new frontend files.
