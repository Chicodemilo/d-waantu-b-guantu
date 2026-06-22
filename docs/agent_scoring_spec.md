# Agent Scoring System

> Epic 28 (Agent Scoring). Builds on the deterministic action-capture layer
> (DWB-417..421, `tool_actions`). Status: spec approved, staged build.

## Goal

Score each agent on a project so the team's relative contribution is visible
and the system can reward good work and flag bad. Scoring is driven by
deterministic signals (ticket outcomes, failures, captured actions) plus human
and peer judgement, never by an agent's self-report.

## Core principle

An **append-only ledger is the source of truth**; the per-agent score is
derived and cached (same pattern as `tracking_log` for time/tokens). Every
point change - auto, human, or peer - is one immutable row carrying a reason.
Nothing is silently mutated: corrections append a reverting row, so the whole
history stays auditable and reversible.

## Two currencies (decided)

- **Reputation** - an agent's standing / rank. Accumulates all-time, cannot be
  spent. This is the leaderboard number.
- **Influence** - a per-sprint budget every agent receives (default 20/sprint).
  Spent to praise or punish peers; resets each sprint. Keeps peer scoring
  scarce and intentional.

Leaderboard shows both the permanent reputation and a per-sprint delta (the
ledger carries `sprint_id`, so the per-sprint rollup is a clean filter).

## DB structure

### `score_event` (ledger)

| column | type | notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `project_id` | FK projects | scores are per-agent-per-project (agents are global) |
| `sprint_id` | FK sprints, nullable | the sprint the event falls in; enables per-sprint view |
| `subject_agent_id` | FK agents | who is scored |
| `delta` | INT signed | +N / -N applied to subject reputation |
| `source` | enum(`auto`,`human`,`peer`) | who initiated |
| `trigger_type` | enum | `ticket_closed`, `rework`, `test_failure`, `stale`, `zero_token_close`, `gate_miss`, `forgot`, `carrot`, `stick`, `peer_grant`, `peer_demerit` |
| `actor_agent_id` | FK agents, nullable | peer who awarded it (null for auto/human) |
| `actor_cost` | INT default 0 | influence the actor spent (peer economy) |
| `reason` | VARCHAR(500), nullable | optional note; auto-generated for system triggers, optional for human/peer |
| `ref_type` / `ref_id` | str / BIGINT, nullable | link to triggering ticket / tool_action / failure_record |
| `reverted_by` | FK score_event, nullable | corrections point back; rows are never deleted |
| `created_at` | DATETIME | |

### `agent_score` (derived cache, rebuildable from the ledger)

| column | notes |
|--------|-------|
| `agent_id` + `project_id` | PK pair |
| `reputation` | sum of all deltas to this agent (all-time) |
| `influence` | spendable per-sprint budget remaining |
| `updated_at` | |

`agent_score` is a cache: a rebuild routine recomputes it from `score_event`
so the ledger is always authoritative.

## Triggers

### Auto (system) - no agent cooperation needed

| Event | Direction | Signal |
|-------|-----------|--------|
| Ticket -> done | up (scale by story points or flat) | `status_history` |
| Done with no rework ever | up bonus | no `rework` failure_record on ticket |
| Ticket reopened after done (rework) | down | `failure_record` type=`rework` |
| Test failure attributed | down per failure | `failure_record` type=`test_failure` |
| Stale ticket (in_progress, no updates) | down small | existing stale-check |
| Closed with 0 tokens | down | existing 0-token alert |
| `forgot` to do something | down small | see below |

Auto-triggers attribute via `ticket.assigned_agent_id` / `failure_record.logged_by`,
NOT the `tool_actions` session attribution - so they credit the correct worker
regardless of the TL-attribution quirk in the capture layer.

The `forgot` class is now detectable from captured data: closed a ticket with
**no commit referencing the key** (`git_hook`), **never moved the ticket to
in_progress** (worked silently), **didn't run tests before closing** (no
`test_result` since sprint start), or **missing code header** (`force_headers`).

### Human - slash commands (free, you are the boss)

- `/carrot <agent> <points> "reason"` - award (`source=human`, `trigger=carrot`)
- `/stick <agent> <points> "reason"` - penalize (`trigger=stick`)
- `/score <agent>` - view an agent's score + recent ledger
- `/leaderboard` - project standings

Reason is optional. Auto-triggers still auto-fill a reason so system events stay
self-describing; human and peer events may omit it (a blank reason weakens the
audit trail for peer scoring, but is allowed).

### Peer economy - agent to agent

Awarding **or** penalizing a peer spends the actor's influence:
`peer-carrot Barry 5` -> actor influence -5, Barry reputation +5;
`peer-stick Sage 5` -> actor influence -5, Sage reputation -5.

Reputation (merit) is separate from influence (the social-currency budget) so
generosity never costs an agent its own rank, and punishing is not free.

**Anti-gaming (built in, all caps tunable in `config/scoring.py`):**
- No self-scoring.
- `MAX_DING_PER_ACTION` (default 5) - the most reputation one peer-stick can
  remove in a single action.
- `MAX_DING_PER_TARGET_PER_SPRINT` (default 10) - the most one agent can dock a
  specific peer across a whole sprint, so no single agent can tank another
  (kills vendettas).
- `MAX_GRANT_PER_TARGET_PER_SPRINT` (default 10) - symmetric cap on awarding, so
  two agents cannot pump each other's reputation (kills collusion rings).
- Total outgoing is additionally bounded by the per-sprint influence budget (20).
- A peer action that would exceed a cap is rejected (or clamped) at the API, not
  silently dropped.
- Influence resets each sprint (no hoarding, keeps it dynamic).
- Every event is ledgered -> brigading is visible and any event is revertible.

## Broadcast notifications

Carrots and sticks are social events - the whole team should feel them, not just
the subject.

- **Human carrot/stick:** broadcasts to ALL project agents at elevated priority,
  flagged as coming from the human (the boss). This is the highest-signal event
  in the system and should land prominently in every agent's view. The subject's
  own notification is phrased directly ("You received +10 from the human:
  <reason>").
- **Peer carrot/stick:** also broadcasts to all project agents, at normal
  priority, so the team sees who is recognizing or docking whom.
- **Auto-triggers do NOT broadcast** (too frequent / mechanical). They surface on
  the leaderboard and in the per-agent ledger only.
- **Mechanism:** reuse the alerts system - per-agent alert rows plus the existing
  send-to-team broadcast. Human events use an elevated severity so they stand out
  from routine alerts.

Belongs to DWB-426 (human tools) and DWB-427 (peer economy).

## Frontend

No new page - scoring slots into the existing surfaces:

- **Team Status section (ProjectPage):** each roster row shows reputation +
  this-sprint delta + influence remaining; the section sorts as a leaderboard
  (top score first). The at-a-glance view.
- **AgentPage:** the per-agent score ledger - the reasoned event history (every
  carrot/stick/auto-trigger with its reason), so you can see why an agent is
  up or down.

Plain CSS, no icons, no em dashes, matching the terminal aesthetic.

## Ticket breakdown (epic 28 / S68)

| Key | Title | Wave |
|-----|-------|------|
| DWB-424 | Scoring ledger: `score_event` + `agent_score` + migration + derived rebuild + read API | 1 (foundation) |
| DWB-425 | Auto-trigger engine: wire ticket_closed / rework / test_failure / stale / zero_token / gate_miss / forgot into the ledger | 1 |
| DWB-428 | Scoring UI: Team Status leaderboard + AgentPage ledger view | 1 |
| DWB-426 | Human tools: `/carrot` `/stick` `/score` `/leaderboard` skills + scoring API | 2 |
| DWB-427 | Peer economy: influence budget, per-sprint reset, peer grant/demerit, anti-gaming caps | 2 |

DWB-424 is the foundation; 425 and 428 build on it (wave 1). Human tools and the
peer economy (wave 2) follow once wave 1 is working.
