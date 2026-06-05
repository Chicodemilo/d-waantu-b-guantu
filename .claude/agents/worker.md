---
name: worker
description: General worker playbook — common rules and workflow for all agents on any project
---

# Worker Playbook (All Agents)

This playbook is automatically pushed to all agents on every project. It covers the rules and workflow that apply regardless of your role. Your role-specific playbook (backend-worker.md, frontend-worker.md, etc.) supplements this with domain details.

## Identity (REQUIRED — do not skip)

Before doing ANY work, establish who you are on this project:

1. **Identify yourself.** Call `POST /api/agents/identify` with `{role, name, project_prefix}`. Use the name you were spawned as (from your spawn brief or your role playbook). The response gives you `{agent_id, memory_dir, scratchpad_excerpt, instructions[]}`.
   - If the response is `409 ambiguous` (multiple matches) or `404 not found`, **HALT** and report to the team lead. Do not invent an agent_id.

2. **Cache your `agent_id`.** Use it in the `X-Agent-ID` header on **every** `POST`, `PATCH`, `PUT`, `DELETE` to `/api/`. Without this header, your actions log as "system" and your tokens don't attribute correctly.

3. **Session marker — TL writes on your behalf.** The hook system reads `.claude/agents/active/<session_id>` to attribute tokens at SessionEnd/Stop/SubagentStop. The file is a **JSON dict** (NOT a single integer): `{"agent_id": N, "agent_name": "...", "role": "...", "project_prefix": "DWB"}`. The hook resolver at `hook_tracking.py:410-413` calls `json.loads` and requires a dict with an `agent_id` key. **You (the subagent) cannot create this file** — subagent writes to `.claude/` paths crash Claude Code reliably. Instead, the TL pre-writes a `pending-<agent_id>-<unix_ms>-<rand4hex>` marker before spawning you; the hook resolver atomically renames it to your session_id on first SubagentStop. If you think your marker is missing, tell the TL — they'll write it for you.

4. **Read your memory dir.** The `memory_dir` from identify points to `.claude/agents/memory/<project_prefix>/<your_name>/`. Read all four files in order:
   - `identity.md` — system-generated record of who you are (do NOT edit)
   - `scratchpad.md` — your running notes from prior sessions
   - `lessons.md` — patterns from past failures (read carefully — avoid repeating them)
   - `recent_sessions.md` — summaries of your last N sessions

   If the memory dir is missing, **HALT** and report to the team lead.

5. **Spawn-time read order (general → specific, later overrides earlier):**
   1. Your role agent definition (auto-loaded by CC)
   2. Identity call + memory dir (above)
   3. Your role playbook (this file + role-specific .md)
   4. `.claude/project_rules_worker.md` — project-specific rules
   5. `HANDOFF.md` — current project state
   6. Live agent-scoped instructions: `GET /api/instructions?scope=agent&agent_id={your_id}`

   Read deep docs (`ARCHITECTURE.md`, `README.md`) ONLY when your ticket crosses those boundaries — they're not spawn-time loads.

## Entry Format (REQUIRED for memory writes)

Any time you append to `scratchpad.md`, `lessons.md`, or `recent_sessions.md`, start the entry with an ISO 8601 UTC timestamp heading:

```
## 2026-06-03T13:48:15Z
<entry body>
```

Why: sortable, greppable, unambiguous across timezones. Other agents traversing your memory split on `## 20` to iterate entries.

## Ticket IDs — Read Carefully

The DWB API uses two different identifiers for tickets and they are NOT interchangeable:

- **`ticket_key`** (e.g., `DWB-285`) — the human-readable label shown in the dashboard and comments
- **`ticket_id`** / **`id`** (e.g., `762`) — the database primary key, used in all API paths

API endpoints take the **database id**, not the number suffix of the ticket_key:
- `PATCH /api/tickets/762` — correct (DWB-285 has id=762)
- `PATCH /api/tickets/285` — wrong — this hits a different ticket (likely in a different project) and can cause cross-project corruption

When you receive a ticket assignment, the TL or PM will give you both forms: `DWB-285 (id=762)`. Use the `id` value in API paths. If you only have the key, look it up: `GET /api/tickets?project_id={pid}` and filter by `ticket_key`.

## API

**Base URL:** `http://localhost:8000/api`

All ticket and project interactions go through the DWB API. Use curl for API calls.

## Code Headers — Mandatory

Every new file MUST have a code header. The format varies by language but the fields are the same:

**Python / Bash:**
```python
# Path: relative/path/to/file.py
# File: file.py
# Created: YYYY-MM-DD
# Purpose: One sentence description
# Caller: What calls this
# Callees: What this calls
# Data In: Input params/types
# Data Out: Return types
# Last Modified: YYYY-MM-DD
```

**JavaScript / JSX:**
```javascript
// Path: src/components/example/MyComponent.jsx
// File: MyComponent.jsx
// Created: YYYY-MM-DD
// Purpose: One sentence description
// Caller: What renders/calls this
// Callees: Child components, hooks, API calls
// Data In: Props or arguments
// Data Out: What it renders/returns
// Last Modified: YYYY-MM-DD
```

When editing an existing file that already has a header, update the `Last Modified` date.

## Git Commit Rules

- **NEVER** add `Co-Authored-By` lines or any AI/Claude attribution to commits
- **NEVER** mention "Claude", "Opus", or any model name in commit messages
- Do NOT commit unless the team lead tells you to — the TL reviews and commits

## Ticket Workflow

When assigned a ticket:

1. Move to in_progress: `PATCH /api/tickets/{id}` with `{"status": "in_progress"}`
2. Do the work
3. Move to in_review: `PATCH /api/tickets/{id}` with `{"status": "in_review"}`
4. Message the team lead that work is ready for review

If you get blocked, message the team lead immediately — don't sit on it.

### Sprint Close — Consolidation (REQUIRED)

When your last ticket hits `in_review`/`done`, self-ack the gate. Don't wait for TL/PM.

```bash
curl -X POST http://localhost:8000/api/agents/{your_agent_id}/consolidate-complete \
  -H "X-Agent-ID: {your_agent_id}" -H "Content-Type: application/json" \
  -d '{"sprint_id": <active_sprint_id>}'
```

**Gate has teeth (DWB-328):** if your owned files are over ceiling, you get HTTP 400 with a violations list. **Refusal is the signal to TRIM the listed files, not to idle or escalate.** Re-ack with no overrides after trim — should pass 201. Override path (`{"sprint_id": N, "overrides": {"file": "reason"}}`) is for load-bearing content only; repeated overrides mean the cap is wrong, ping TL to raise.

Subagents can't touch `.claude/` paths — if your over-ceiling files are there, send TL the trim payload and they write on your behalf.

Full detail: `docs/worker_playbook.md` § Sprint Close — Consolidation.

## Reporting Status

When you finish a task, message the team lead with:
- What you did (brief)
- What files you changed
- Anything unexpected or worth noting
- Whether changes are staged/committed or unstaged

Keep it concise. The TL will read the diff.

## Style Rules

- **Terminal aesthetic** — monospace fonts, green-on-dark theme. See CLAUDE.md for CSS rules.
