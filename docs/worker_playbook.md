# Worker Playbook (All Agents)

> Common rules and workflow for all agents. Loaded automatically alongside TL/PM playbooks.
> Your role-specific playbook (`.claude/agents/{role}.md`) supplements this.

---

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself.

## On Spawn — Read These First

Before doing anything, read: (1) `.claude/agents/{role}.md`, (2) `.claude/project_rules_worker.md`, (3) `HANDOFF.md`, (4) `ARCHITECTURE.md`, (5) `README.md`. If any are missing, proceed with what you have and flag it.

## API

**Base URL:** `http://localhost:8000/api` — All ticket/project interactions go through the DWB API. Use curl.

## Code Headers — Mandatory

Every new file MUST have a code header. See `docs/rules/global/code-header-format.md` for the format. When editing a file that already has a header, update the `Last Modified` date.

## Git Commit Rules

- **NEVER** add `Co-Authored-By` lines or any AI/Claude attribution to commits.
- **NEVER** mention "Claude", "Opus", or any model name in commit messages.
- Do NOT commit unless the TL tells you to — the TL reviews and commits.

## Ticket Workflow

When assigned a ticket: (1) PATCH `/api/tickets/{id}` with `{"status": "in_progress"}`, (2) do the work, (3) PATCH with `{"status": "in_review"}`, (4) message the TL that work is ready. If blocked, message the TL immediately — don't sit on it.

## Reporting Status

When done, message the TL: what you did, files changed, anything unexpected, whether changes are staged/committed or unstaged. Keep it concise — the TL will read the diff.

## Style Rules

- **Plain CSS only** — no Tailwind, no CSS-in-JS, no styled-components. Styles in `.css` files.
- Use **CSS custom properties** from `theme.css` for colors and fonts.
- **Terminal aesthetic** — monospace fonts, green-on-dark theme. Applies to all UI-facing content.

## STOP Means Stop

When the user says **STOP**, **PAUSE**, or **HALT**: immediately cease ALL activity. No tool calls, no messages, no cleanup. This overrides everything.
