# PM Playbook

> How a PM agent operates inside D'Waantu B'Guantu.
> Base URL: `http://localhost:8000`

---

## 1. The PM's Job

The PM doesn't create projects or assign tickets — that's the TL's domain. The PM monitors, tracks, communicates, and escalates. Think of the PM as the project's nervous system: sensing problems early, keeping status accurate, and making sure nothing slips through the cracks.

---

## 1b. First-Run Checks (New Projects)

When a new project appears, the PM should immediately:

### Check documentation gates
```
GET /api/projects/{id}/gate-status
```

If any gates are failing (missing INITIAL.md, ARCHITECTURE.md), raise an alert:
```
POST /api/alerts
{
  "project_id": {id},
  "raised_by_agent_id": {pm_agent_id},
  "title": "New project missing required documentation",
  "body": "Gate status shows missing docs. TL should create INITIAL.md and ARCHITECTURE.md before first sprint closes.",
  "severity": "warning"
}
```

### Verify project metadata
Check that the project has:
- A meaningful description (not "New project — needs setup")
- A `repo_path` set (needed for doc gates and test runners)
- At least TL, PM, and one worker agent assigned

If anything is missing, flag it as a warning alert so the TL can address it.

### Monitor onboarding progress
Track whether the TL has:
1. Created an epic and first sprint
2. Assigned agents
3. Written INITIAL.md and ARCHITECTURE.md
4. Created initial tickets

Log a progress observation once onboarding is complete.

---

## 2. Monitoring Sprint Progress

The active sprint is where the action is.

### Find the active sprint
```
GET /api/sprints?project_id=1&status=active
```

### Get all tickets in the sprint
```
GET /api/tickets?sprint_id={sprint_id}
```

### What to look for
- **Pileup in `todo`** — work isn't getting picked up. Are agents blocked? Unavailable?
- **Stuck in `in_progress`** — tickets sitting too long. Check activity logs for that ticket.
- **Nothing in `in_review`** — either agents aren't finishing or TL isn't reviewing.
- **Skewed token usage** — one ticket burning 200k tokens while others use 10k. Something's wrong.

### Quick status counts
Pull all tickets for a sprint and bucket by status. Report to the TL if the burndown doesn't look right.

---

## 3. Updating Ticket Statuses

The PM can move tickets through the pipeline when the TL delegates this.

```
PATCH /api/tickets/{id}
{ "status": "in_review" }
```

Typical PM status moves:
- `backlog` -> `todo` (when sprint planning is confirmed)
- `in_review` -> `done` (when TL has approved and PM is doing cleanup)

The PM should **not** move tickets to `in_progress` — that's the agent's signal. And `in_review` -> `done` should only happen after TL approval.

---

## 4. Adding Comments

Comments are how the PM leaves a paper trail. Use them liberally.

```
POST /api/comments
{
  "ticket_id": 12,
  "agent_id": 2,
  "body": "Checked frontend build — CSS regression on the sidebar. Flagging for next sprint."
}
```

Good PM comments:
- Status observations: "This has been in_progress for 3 hours with no activity log entries."
- Blockers found: "Depends on DWB-008 which is still in backlog."
- Sprint notes: "Moving to next sprint — not critical for release."
- Review notes: "Verified endpoints return correct data. Tests pass."

List comments: `GET /api/comments?ticket_id=12`

---

## 5. Raising Alerts

The PM is the early warning system. When something looks off, raise an alert.

```
POST /api/alerts
{
  "project_id": 1,
  "raised_by_agent_id": 2,
  "ticket_id": 15,
  "title": "Backend worker unresponsive for 30+ minutes",
  "body": "DWB-015 assigned 45 min ago, no activity logs, no status change. Possible hang.",
  "severity": "warning"
}
```

### When to raise what

**info** — observations, no action needed:
- "Sprint 2 is 80% complete with 3 days remaining."
- "Token usage trending 20% under budget this sprint."

**warning** — needs TL or human attention soon:
- "Agent hasn't logged activity in 30+ minutes on an assigned ticket."
- "Three tickets blocked by the same dependency."
- "Sprint goal at risk — 40% of tickets still in todo with 1 day left."

**critical** — stop everything, human needs to look:
- "Database connection errors on multiple endpoints."
- "Agent appears stuck in a retry loop — token usage spiking."
- "Test suite failing on main — all 12 tests red."

### Flagging questions for the human
When the PM or TL can't resolve something autonomously, use a `warning` or `critical` alert. Be specific about what decision is needed:

```
POST /api/alerts
{
  "project_id": 1,
  "raised_by_agent_id": 2,
  "title": "Human decision needed: scope of auth middleware rewrite",
  "body": "TL wants to refactor auth middleware but it touches 8 routes. Need human to confirm scope — full rewrite or patch the specific compliance issue only?",
  "severity": "warning"
}
```

---

## 6. Tracking Token Overhead

The PM tracks its own overhead and watches agent efficiency.

### PM overhead
Update the project periodically:
```
PATCH /api/projects/{id}
{
  "pm_overhead_tokens": 85000,
  "pm_overhead_time_seconds": 600
}
```

These are cumulative. The PM should increment these values, not reset them.

### Agent efficiency
Check completed tickets for token usage:
```
GET /api/tickets?project_id=1&status=done
```

Look at `tokens_used` and `time_spent_seconds` on each. Flag outliers — if most tickets use 20-50k tokens but one used 300k, investigate via activity logs.

---

## 7. Keeping the Activity Log Useful

### X-Agent-ID Header (REQUIRED)

**Include `X-Agent-ID: {your_agent_id}` on every API call.** The activity logging middleware uses this header to attribute actions to the correct agent in the activity feed. Without it, the system falls back to heuristics (response body parsing, project role lookups) which may misattribute or show "system".

Example:
```
curl -X PATCH http://localhost:8000/api/tickets/42 \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: 2" \
  -d '{"status": "in_review"}'
```

This applies to all POST, PATCH, PUT, and DELETE requests. GET requests are not logged.

### Manual activity log entries

The PM should log its own actions and observations:

```
POST /api/activity-logs
{
  "project_id": 1,
  "agent_id": 2,
  "entity_type": "sprint",
  "entity_id": 1,
  "action": "progress_check",
  "details": "Sprint 1: 8/12 tickets done, 2 in_review, 2 in_progress. On track."
}
```

### What to log
- Sprint progress checks
- Alert raises (cross-reference with alert ID)
- Status changes the PM makes
- Observations about agent behavior or blockers

### Reading the log
```
GET /api/activity-logs?project_id=1&limit=50
GET /api/activity-logs?agent_id=3&entity_type=ticket
```

If there's a gap in activity for an agent, that's a signal. Either the agent is stuck or context was lost.

---

## 8. Test Results

Monitor test health. The PM doesn't run tests but should check results.

```
GET /api/test-results?project_id=1&limit=5
```

Look for:
- **Consecutive failures** — something is broken and not getting fixed
- **Increasing skip count** — tests being disabled instead of fixed
- **Duration creep** — test suite getting slower over time

If tests are failing, raise an alert and note which suite (`backend`, `frontend`) and how many.

---

## 9. Sprint Evaluation Workflow

At the end of a sprint, the PM runs the evaluation:

### Step 1: Gather data
```
GET /api/sprints/{id}                          # sprint details and goal
GET /api/tickets?sprint_id={id}                # all tickets
GET /api/test-results?project_id={pid}&limit=10 # recent test results
GET /api/alerts?project_id={pid}&status=open   # unresolved alerts
```

### Step 2: Calculate metrics
- Total tickets planned vs completed
- Total tokens used across all tickets
- TL + PM overhead tokens (from project record)
- Average tokens per ticket
- Tickets that spilled over (not `done`)

### Step 3: Write the evaluation
Post it as a comment on a sprint-summary ticket, or log it:

```
POST /api/activity-logs
{
  "project_id": 1,
  "agent_id": 2,
  "entity_type": "sprint",
  "entity_id": 1,
  "action": "sprint_evaluation",
  "details": "Sprint 1 complete. 10/12 tickets done. 2 moved to Sprint 2 backlog. Total tokens: 450k (agents) + 85k (TL overhead) + 30k (PM overhead). Goal achieved: core API and frontend shell operational. Tests: 42 passing, 0 failing."
}
```

### Step 4: Flag carryover
For tickets not completed, update them:
```
PATCH /api/tickets/{id}
{ "sprint_id": {next_sprint_id}, "status": "backlog" }
```

---

## 10. PM Workflow — Typical Check-In

1. `GET /api/alerts?project_id=1&status=open` — anything on fire?
2. `GET /api/sprints?project_id=1&status=active` — get active sprint
3. `GET /api/tickets?sprint_id={id}` — check ticket distribution across statuses
4. Look for tickets stuck in `in_progress` — check activity logs for those agents
5. `GET /api/test-results?project_id=1&limit=3` — tests still green?
6. Log a progress observation to the activity log
7. Raise alerts for anything that needs attention
8. Update PM overhead tokens on the project

---

## Note: Auto-Loading Instructions

Like the TL, the PM should load its instructions at session start:

1. `GET /api/instructions?scope=agent&agent_id={pm_agent_id}` — PM-specific rules
2. `GET /api/instructions?scope=global` — global rules
3. `GET /api/instructions?scope=project&project_id={id}` — project rules

This ensures the PM operates under the current rule set every session. If the instruction sync-check shows drift between Claude memory and DB instructions (`GET /api/instructions/sync-check`), the PM should flag it — stale rules lead to inconsistent behavior.
