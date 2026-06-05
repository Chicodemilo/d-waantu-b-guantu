# Worker Playbook (All Agents)

> Common rules and workflow for all agents. Loaded automatically alongside TL/PM playbooks.
> Your role-specific playbook (`.claude/agents/{role}.md`) supplements this.

---

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself.

## Canonical Tools

> **If your project does not have Jira enabled (`project.jira_base_url` is null), skip this section** — use the DWB API directly for ticket transitions (`PATCH /api/tickets/{id}` with `{"status": "..."}` + `X-Agent-ID` header). The D2J CLI is only relevant for Jira-linked projects.

All ticket operations go through the D2J (DWB_2_JIRA) CLI — it keeps Jira and DWB in lockstep.

- **Transition your ticket:** `dwb2jira ticket transition POR-KEY --to "In Progress"` — atomic dual-write (Jira + DWB)
- **Pull your ticket:** `dwb2jira report --jira POR-KEY` or `dwb2jira report` (defaults to your assigned work)
- **Never** PATCH `/api/tickets/{id}` directly for status changes — it updates DWB only and leaves Jira drift. `dwb2jira ticket transition` is the canonical move.
- **Never** use `dwb2jira ticket update --status` for status changes either — it updates Jira only and leaves DWB drift. `ticket transition` is dual-write aware; `ticket update` is not.
- **If a teammate already did one of the above by mistake:** treat it like a bail-forward drift — tell the TL, PM does a one-sided DWB PATCH to realign. Don't try to un-do it yourself.
- **D2J defaults to the project_id set in your D2J config; verify with `dwb2jira config show`.** If you need to operate on a different project than your shell's default (e.g. transitioning a D2J self-management ticket from a non-D2J working dir), prefix with `DWB_PROJECT_ID=N dwb2jira ticket transition ...` so the twin lookup hits the right project. Otherwise the dual-write falls back to Jira-only with a "no twin" warning.

Full reference: `~/Dev/DWB_2_JIRA/README.md`. Status vocabulary (terminal vs non-terminal, Jira↔DWB mapping): `~/Dev/DWB_2_JIRA/README.md §Terminal vs non-terminal status vocabulary`.

## On Spawn — Identity (REQUIRED)

Before doing ANY work, establish who you are on this project:

1. **Identify yourself.** `POST /api/agents/identify` with `{role, name, project_prefix}` (use the name from your spawn brief; for fixed-role agents this may be a `_<PROJECT_PREFIX>` suffixed form like `Archie_DWB`, but the endpoint accepts the short name too). Response: `{agent_id, memory_dir, scratchpad_excerpt, instructions[]}`.
   - On `409 ambiguous` or `404 not found`: **HALT** and tell the TL. Never invent an agent_id.
2. **Cache your `agent_id`.** Include `X-Agent-ID: {agent_id}` on **every** `POST`/`PATCH`/`PUT`/`DELETE` to `/api/`. Without it, your actions log as "system" and your tokens don't attribute.
3. **Session marker — TL writes on your behalf.** The hook resolver reads `.claude/agents/active/<session_id>` (JSON dict with an `agent_id` key) to attribute tokens at SessionEnd/Stop/SubagentStop. **You cannot create this file** — subagent writes to `.claude/` paths crash Claude Code. The TL pre-writes a `pending-<agent_id>-<unix_ms>-<rand4hex>` marker before spawning you; the resolver atomically renames it to your session_id on first SubagentStop. If you think your marker is missing, tell the TL — they write it.
4. **Read your memory dir.** The `memory_dir` returned by identify points to `.claude/agents/memory/<project_prefix>/<your_name>/`. Read `identity.md`, `scratchpad.md`, `lessons.md`, `recent_sessions.md` in that order. If missing, **HALT** and tell the TL.

## On Spawn — Read These First

After identity, read: (1) `.claude/agents/{role}.md`, (2) `.claude/project_rules_worker.md`, (3) `HANDOFF.md`, (4) `ARCHITECTURE.md`, (5) `README.md`. If any are missing, proceed with what you have and flag it.

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

**Custom project statuses:** any non-terminal review-ish label (e.g. `In Review`, `Code Review`, `QA`) maps to `in_review`; any terminal label maps to `done`. If you're unsure, run `ticket get POR-KEY` first and ask the TL if the mapping isn't obvious.

### Return + failure recovery

**If TL returns the ticket:** TL runs `dwb2jira ticket transition POR-KEY --to "In Progress"` to send it back, and messages you with feedback. Re-read ticket comments for context, do the fixes, re-hand-off via step 3.

**If `ticket transition` fails** (Jira 4xx/5xx, network error): `dwb2jira log --failures --tail 5` shows recent failures with response bodies. Other `log` flags (`--command`, `--since`, `--json`) are in README §Legacy CLI Reference. Escalate to TL — don't retry blindly; auth/permission errors can't be self-resolved.

**Bail-forward: Jira succeeded but DWB PATCH failed.** The command will warn that the DWB twin is out of sync. Jira is NOT rolled back. **DO NOT re-run `ticket transition`** — it would re-attempt Jira and could double-transition. Tell the TL; PM does a one-sided DWB PATCH to realign:

```bash
curl -X PATCH http://localhost:8000/api/tickets/{dwb_id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"status": "<mapped-dwb-status>"}'
```

(PM owns that recovery — it's in their playbook § 4 Exception (a). Shown here so you can sanity-check the fix.)

If you get blocked on the work itself, message the TL immediately — don't sit on it.

## Sprint Close — Consolidation (REQUIRED)

DWB enforces a `force_consolidation` gate at sprint close. Every sprint participant must call `consolidate-complete` before the TL can close the sprint. The gate has TEETH (DWB-328): the ack endpoint REFUSES with HTTP 400 if your owned files are over ceiling, unless you provide per-file overrides with non-empty reasons.

**When to ack:** as soon as your last ticket hits `in_review` (or `done`). Don't wait for the TL — the ack is yours to file.

**How:**

```bash
curl -X POST http://localhost:8000/api/agents/{your_agent_id}/consolidate-complete \
  -H "X-Agent-ID: {your_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": <active_sprint_id>}'
```

201 on success. 409 if already acked. 400 if over-ceiling files exist (see below).

**Check your owned files BEFORE acking:**

```
GET /api/projects/{project_id}/consolidation-status?sprint_id=<active_sprint_id>
```

Your block lists `owned_over_ceiling_files`. If non-empty: trim before acking.

### REFUSAL is the signal to TRIM, not idle (DWB-328 autonomy)

When the gate refuses your ack with violations:

1. **Default path: TRIM the listed files.** That's the work. Re-ack with no overrides. Should pass clean. Don't wait for TL guidance — refusal means go fix.
2. **Override path (rare): per-file reason.** Use only when the file is genuinely load-bearing and trim would lose meaning. Body: `{"sprint_id": N, "overrides": {"file_path": "non-empty reason text", ...}}`. Every file in the violation list must have a key. Empty/whitespace reasons rejected.
3. **Cap-raise path (when override would repeat across sprints):** ping TL with proposed `_TOKEN_CEILINGS` change. Don't override the same file every sprint.

**Subagents can't write to `.claude/` paths.** If your over-ceiling files live under `.claude/agents/memory/<name>/` or `.claude/agents/<role>.md` etc, send the TL the trim payload via SendMessage and they'll write it on your behalf. Then retry.

**Idling on refusal is the anti-pattern.** The TL doesn't want to nag every agent every sprint to trim their files. The system tells you what's over; you trim; you retry. That's the contract.

## Reporting Status

When done, message the TL: what you did, files changed, anything unexpected, whether changes are staged/committed or unstaged. Keep it concise — the TL reads the diff.

## Style Rules

Project-specific style rules (CSS conventions, UI aesthetic, framework bans) live in `.claude/project_rules_worker.md`. Read them at session start.

## STOP Means Stop

When the user says **STOP**, **PAUSE**, or **HALT**: immediately cease ALL activity. No tool calls, no messages, no cleanup. This overrides everything.
