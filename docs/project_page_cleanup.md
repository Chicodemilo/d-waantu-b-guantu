# Project page cleanup

Audit of `/projects/:id` (`frontend/src/pages/ProjectPage.jsx`, 554 lines),
2026-10-06. Measured against DWB's live data rather than read off the code, so
the "this panel is empty" claims are observations, not predictions.

Miles's framing, which sets the order: **start with what is better seen
somewhere else.** Those cuts are provable rather than taste, so they do not
need a design discussion first.

## What is on the page now

```
ProjectHeader
MemoryTransitionOverlay
Tools (collapsible)
  Project Actions · Sprint Gates (5 toggles) · Doc Gates (4 toggles)
  Inter-Agent Comms · Jira Integration · MemoryModeToggle
ConsolidationStatus   <- commented out 2026-06-08, import still live
Alerts
Current Sprint | Recent Activity
Time & Tokens
Token Budget
Velocity
Epics
Team Status
Standards Audits
links: View All Tickets · View Jira Issues
```

Eight full-width stacked panels below the fold plus the alert block.

## Tier 1: strict duplicates of a page that already exists

Each is provably redundant. No judgement call about what matters.

### 1. Standards Audits -> `/projects/:id/audits`

The panel and `AuditsPage` call the same hook, `useStandardsAudits`. The page
adds a summary header with pass/reject counts and rows that expand in place to
show violations and the per-agent scorecard. The panel has none of that, and on
DWB renders empty permanently because `force_standards_audit` is OFF — the
endpoint returns `[]`. Strictly less information, same source. Easiest delete.

### 2. Team Status -> `/projects/:id/agents`

`LiveSessions`' own header describes it as "per-project agent roster rendered as
a scoring leaderboard", from `getProjectTeam` + `getProjectScores`.
`ProjectAgentsPage` is a tabbed **Roster | Scoreboard** on the same
`getProjectScores`, where the Scoreboard tab IS the full leaderboard.

**Do not delete blind.** The panel owns the stale-ticket POST to
`/api/tickets/stale-check` with its 10/20/30 minute thresholds, and its header
says that lives there because it is coupled to the agent/ticket join. That logic
must move, not vanish. Own ticket, not a footnote on the delete.

### 3. Recent Activity: filter, do not delete -> `/projects/:id/comms`

Composition of the last 90 rows on DWB:

| action | count |
|---|---|
| message_sent (SendMessage) | 35 |
| file_written (Edit/Write) | 22 |
| notification | 19 |
| status_changed | 8 |
| session opened/closed | 4 |
| created/updated | 2 |

76 of 90 are `tool_action`. The 35 SendMessage rows have a dedicated home in
`InterAgentCommsPage` (dense, newest-first, polls every 3s) which the Tools
panel already links to. The 19 notifications are mostly "Claude is waiting for
your input", which is not project activity at all.

Keep the panel, filter to `entity_type in (ticket, session)`. That is the 14
rows of 90 that are actually project events.

### 4. ConsolidationStatus: dead code

Commented out 2026-06-08 with a "pending rethink" note. Four months. The import
at the top of the file is still live. Goes with the above.

## Tier 2: the biggest visual problem, and it is not a layout problem

**Alerts.** 86 open on DWB. **80 are category `scoring` at severity
`critical`** — 93% of the queue, all from Sept 29-30. These are reputation
carrot/stick broadcasts raising critical. The largest mass on the page is one
stale category shouting at maximum severity, and it is why the 3 actionable and
3 comms alerts are invisible.

DWB-598 already names this ("reputation broadcasts raise critical, so critical
stops meaning anything") and sits in backlog. **Fixing that ticket does more for
this page than any layout change.** Do it before redesigning the alert block.

## Tier 3: needs a destination built, not just moved

- **Epics** — 26 rows in a scroll box, 21 completed, 1 in progress, 4 open. 80%
  archive. `EpicPage` is per-epic; there is no epic LIST page, so this needs a
  home built rather than a link added.
- **Time & Tokens / Token Budget / Velocity** — three consecutive token panels,
  plus `tl_overhead_tokens`/`pm_overhead_tokens` in the header. `SessionsPage`
  carries per-session rollups so there is partial overlap, but the lifetime view
  is not strictly duplicated. Leave until the clear wins are done.
- **Doc Gates vs Sprint Gates** — two sections, nine toggles, one mechanism.
  `force_coding_standards_md` (the doc exists) and `force_standards_audit` (the
  code conforms) are in different sections while one tooltip explains they
  complement each other. Merge.

## Side finding, correctly scoped

`/api/tokens/audit` accepts `project_id` and silently ignores it — the function
signature has no such parameter, so it returns every agent system-wide. Found
because project 1's audit listed `Pixel_CI` and `Sylvie_IND`.

**NOT on this page.** The project page's Token Budget is a different component
and the dashboard's caller passes no param, so nothing currently displays wrong
data. It is a latent trap of the same family as three other defects found the
same day: a parameter accepted and discarded, answered 200.

## The read worth keeping

The page's problem is not panel count. **Nothing on it is scoped to "what do I
need right now."** It shows every fact DWB knows about a project, at equal
weight, forever. Gates belong in Tools, where they already are. The archive —
completed epics, velocity history, past audits — belongs on its own page. What
belongs here is the active sprint, what is blocking, and who is working.

## Doing the work

Tier 1 is roughly 40 lines out of `ProjectPage.jsx` plus two dead imports. Real
work, so it wants tickets and a worker rather than a TL edit. The stale-ticket
relocation in cut 2 is the only piece with actual risk and should be its own
ticket.
