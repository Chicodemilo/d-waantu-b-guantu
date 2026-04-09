# Handoff: Enforcing Playbook Reading on Session Start

## Problem
TL and PM agent definitions tell agents to "read the playbook on startup" but nothing enforces it. TL skipped reading the playbook and jumped to writing code directly — violating core role boundaries.

## Option 1: Inline Critical Rules into Agent Definitions

Move the non-negotiable rules from the playbooks directly into `.claude/agents/team-lead.md` and `.claude/agents/pm.md`. These files ARE the prompt loaded when agents spawn — content there is guaranteed in context.

**What to inline (TL):**
- TL never writes code — always delegate via tickets
- TL doesn't do ticket housekeeping — that's PM's job
- Code review gate: read changed files before marking tasks complete
- Sprint workflow: PM creates tickets, TL assigns, workers execute

**What to inline (PM):**
- PM owns all ticket creation/closure
- PM must be proactive — don't wait for TL to ask for status
- Sprint gate enforcement before close
- Failure record review is PM's responsibility

**Keep the full playbooks** (`docs/team_lead_playbook.md`, `docs/pm_playbook.md`) as detailed reference, but don't rely on agents choosing to read them.

**Pros:** Simple, no infrastructure changes, guaranteed in context.
**Cons:** Agent definition files get longer. Need to keep them in sync with playbooks.

## Option 2: Hook-Based Enforcement

Use Claude Code `PreToolUse` hooks to physically block TL from editing code.

Example in `.claude/settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hook": "scripts/check_tl_no_code.sh"
      }
    ]
  }
}
```

The script would check if the calling agent is `team-lead` and block the edit with an error message like "TL cannot edit code — assign to a worker."

**Pros:** Hard enforcement — physically impossible to violate.
**Cons:** Heavier. Need to identify calling agent reliably in hook context. May block legitimate TL edits (playbooks, docs, handoff files). Would need an allowlist for non-code files.

## Recommendation

Start with Option 1. It's simpler and covers the 90% case. If TL still drifts, layer on Option 2 as a guardrail.
