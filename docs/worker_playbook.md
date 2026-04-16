# Worker Playbook (All Agents)

> Common rules and workflow for all agents on any project.
> This playbook is automatically deployed to every project alongside the TL and PM playbooks.
> Your role-specific playbook supplements this with domain details.

---

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself.

## On Spawn — Read These First

When you start a session, read these files before doing anything else:

1. **Your role-specific playbook** — `.claude/agents/{role}.md` (if it exists)
2. **Your project rules** — `.claude/project_rules_worker.md` (project-specific rules)
3. **HANDOFF.md** — session continuity notes (current state, decisions, gotchas)
4. **ARCHITECTURE.md** — system design and data model
5. **README.md** — project overview, setup, API reference

This gives you full context without needing to ask the TL. If any of these files don't exist, proceed with what you have and flag it.

---

## API

**Base URL:** `http://localhost:8000/api`

All ticket and project interactions go through the DWB API. Use curl for API calls.

---

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

---

## Git Commit Rules

- **NEVER** add `Co-Authored-By` lines or any AI/Claude attribution to commits
- **NEVER** mention "Claude", "Opus", or any model name in commit messages
- Do NOT commit unless the team lead tells you to — the TL reviews and commits

---

## Ticket Workflow

When assigned a ticket:

1. Move to in_progress: `PATCH /api/tickets/{id}` with `{"status": "in_progress"}`
2. Do the work
3. Move to in_review: `PATCH /api/tickets/{id}` with `{"status": "in_review"}`
4. Message the team lead that work is ready for review

If you get blocked, message the team lead immediately — don't sit on it.

---

## Reporting Status

When you finish a task, message the team lead with:
- What you did (brief)
- What files you changed
- Anything unexpected or worth noting
- Whether changes are staged/committed or unstaged

Keep it concise. The TL will read the diff.

---

## Style Rules

- **Plain CSS only** — no Tailwind, no CSS-in-JS, no styled-components. Styles go in `.css` files.
- **CSS custom properties** from `theme.css` for colors and fonts
- **Terminal aesthetic** — monospace fonts, green-on-dark theme

These apply to everyone, not just frontend. If you're generating UI-facing content (help text, error messages, HTML templates), follow the aesthetic.

---

## STOP Means Stop

When the user says **STOP**, **PAUSE**, or **HALT**: immediately cease ALL activity. No tool calls, no messages, no cleanup. This overrides everything.
