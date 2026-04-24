# Worker Playbook (All Agents)

> Common rules and workflow for all agents. Loaded automatically alongside TL/PM playbooks.
> Your role-specific playbook (`.claude/agents/{role}.md`) supplements this.

---

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself.

## Canonical Tools

All ticket operations go through the D2J (DWB_2_JIRA) CLI — it keeps Jira and DWB in lockstep.

- **Transition your ticket:** `dwb2jira ticket transition POR-KEY --to "In Progress"` — atomic dual-write (Jira + DWB)
- **Pull your ticket:** `dwb2jira report --jira POR-KEY` or `dwb2jira report` (defaults to your assigned work)
- **Never** PATCH `/api/tickets/{id}` directly for status changes — it updates DWB only and leaves Jira drift. `dwb2jira ticket transition` is the canonical move.
- **Never** use `dwb2jira ticket update --status` for status changes either — it updates Jira only and leaves DWB drift. `ticket transition` is dual-write aware; `ticket update` is not.

Full reference: `~/Dev/DWB_2_JIRA/README.md`. Status vocabulary (terminal vs non-terminal, Jira↔DWB mapping): `~/Dev/DWB_2_JIRA/README.md §Terminal vs non-terminal status vocabulary`.

## On Spawn — Read These First

Before doing anything, read: (1) `.claude/agents/{role}.md`, (2) `.claude/project_rules_worker.md`, (3) `HANDOFF.md`, (4) `ARCHITECTURE.md`, (5) `README.md`. If any are missing, proceed with what you have and flag it.

## API

**Base URL:** `http://localhost:8000/api` — used by `dwb2jira` and for GET queries. Mutating ticket calls go through `dwb2jira` (see Canonical Tools above).

## Code Headers — Mandatory

Every new file MUST have a code header. See `docs/rules/global/code-header-format.md` for the format. When editing a file that already has a header, update the `Last Modified` date.

## Git Commit Rules

- **NEVER** add `Co-Authored-By` lines or any AI/Claude attribution to commits.
- **NEVER** mention "Claude", "Opus", or any model name in commit messages.
- Do NOT commit unless the TL tells you to — the TL reviews and commits.

## Ticket Workflow

### Discover first (if unsure)

If you don't know what transitions are valid on your assigned ticket — or if this project uses non-standard status labels — run this before anything:

```
dwb2jira ticket get POR-KEY
```

Lists the current status + available transitions. Use the exact transition label from this output in your next command.

### Pick up → work → hand off

1. **Pick up:** `dwb2jira ticket transition POR-KEY --to "In Progress"` (dual-writes Jira + DWB).
2. **Do the work.**
3. **Hand off:** `dwb2jira ticket transition POR-KEY --to "Ready for Testing/Review" --comment "<commit sha or summary>"`
   — **Example:** `--comment "abc1234 — added /claims endpoint + 6 tests, all green, unstaged"`
   — **Run the transition BEFORE messaging the TL** — the ticket state should be truth when the TL looks.
4. **Message the TL** that work is ready for review. Include: what you did, files changed, staged/committed status, anything unexpected.

### Jira → DWB status mapping

If you see a DWB-side warning, this is what the tool maps to on the twin:

| Jira target | DWB status |
|-------------|------------|
| `To Do` | `todo` |
| `In Progress` | `in_progress` |
| `Ready for Testing/Review` | `in_review` |
| `Done` / `Resolved` / `Closed` / `Won't Do` | `done` |

### Return + failure recovery

**If TL returns the ticket:** TL runs `dwb2jira ticket transition POR-KEY --to "In Progress"` to send it back, and messages you with feedback. Re-read ticket comments for context, do the fixes, re-hand-off via step 3.

**If `ticket transition` fails** (Jira 4xx/5xx, network error): `dwb2jira log --failures --tail 5` shows recent failures with response bodies. Escalate to TL — don't retry blindly; auth/permission errors can't be self-resolved.

**Bail-forward: Jira succeeded but DWB PATCH failed.** The command will warn that the DWB twin is out of sync. Jira is NOT rolled back. **DO NOT re-run `ticket transition`** — it would re-attempt Jira and could double-transition. Tell the TL; PM does a one-sided DWB PATCH to realign:

```bash
curl -X PATCH http://localhost:8000/api/tickets/{dwb_id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"status": "<mapped-dwb-status>"}'
```

(PM owns that recovery — it's in their playbook § 4 Exception (a). Shown here so you can sanity-check the fix.)

If you get blocked on the work itself, message the TL immediately — don't sit on it.

## Reporting Status

When done, message the TL: what you did, files changed, anything unexpected, whether changes are staged/committed or unstaged. Keep it concise — the TL reads the diff.

## Style Rules

Project-specific style rules (CSS conventions, UI aesthetic, framework bans) live in `.claude/project_rules_worker.md`. Read them at session start.

## STOP Means Stop

When the user says **STOP**, **PAUSE**, or **HALT**: immediately cease ALL activity. No tool calls, no messages, no cleanup. This overrides everything.
