# Phase 2 Roadmap — Product Maturity

## 1. README with Complete Usage
- Internal links, complete usage examples, explanations
- How to set up, how to create projects, how agents work
- How sprints/epics/tickets flow
- How testing works, how gates work
- How instructions/playbooks work
- API reference or link to it

## 2. Rules in Repo
- Move all instructions/rules from Claude memory into repo files
- CLAUDE.md, .claude/rules/, or similar
- Alive when we push to GitHub — not trapped in Claude's memory
- Sync mechanism already exists (sync_instructions.py) — extend it

## 3. Forced Project Documentation (Toggle-based)
- INITIAL.md — requirements and phases (forced on project creation?)
- ARCHITECTURE.md — system design
- Planning phase enforcement
- Toggle per project (like sprint gates): force_initial_md, force_architecture_md
- Show in Tools section on project page
- Question: force at project creation or allow retroactive?

## 4. Test Performance Tab
- New tab on tests page: "Performance"
- Track test latency and throughput per run
- Chart over time — are tests getting slower? faster?
- Need to save: per-test duration (already in details JSON), total duration (already saved)
- Frontend: line chart or bar chart of duration over time, slowest tests list

## 5. Failure Analysis Tab (CRITICAL — New Feature)
- New tab on tests page: "Failure Analysis"
- NOT test failures — TEAM failures
- Track when a ticket fails and needs rework (2 attempts = 1 failure)
- Failure taxonomy:
  A. Agent Context Degradation — agent lost track of what it was doing
  B. Spec Drift — requirements changed or were misunderstood mid-sprint
  C. Sycophantic Confirmation — agent agreed instead of pushing back
  D. Tool Selection Error — wrong tool used (name the tool in failure notes)
  E. Cascading Failure — one agent's failure caused multiple failures
  F. Silent Failure — model invented plausible output or hardcoded values
- Multiple views (toggleable):
  - By failure type (pie/bar)
  - By agent (who fails most?)
  - By sprint (when do failures cluster?)
  - Over time (trend)
- Needs new DB model: failure_record or similar
- Needs UI for logging failures (who logs them? PM? TL?)

## 6. Architecture Document
- Question: create now or wait for the toggle requirement?
- If now: document current system architecture
- If wait: build the toggle first, then the doc satisfies its own requirement
- Recommendation: TBD — discuss with team

## Priority Discussion
- Items 1-2 are documentation — low risk, high value
- Item 3 is a feature with toggles — medium complexity
- Item 4 is data we already have, just needs visualization — medium
- Item 5 is a NEW system — high complexity, high value
- Item 6 depends on 3

## Team Input (Collected)

### PM (Mona)
- Log failures both real-time (ticket moves backwards) AND during sprint eval
- Needs ticket status change history to detect rework patterns
- Taxonomy addition: G. Integration Failure — works in isolation, breaks when combined
- Forced docs should be toggleable, not required at creation
- Priority: rules in repo → README → doc toggles → architecture → test perf → failure analysis

### Backend (Devin)
- failure_records schema: VARCHAR failure_type (not enum), severity, attempt_number, root_cause, resolution, resolved flag
- Test perf is 80% frontend, 20% backend (convenience endpoints)
- Per-test durations currently all 0 — need to fix pytest reporter

### Frontend (Pixel)
- All visualizations achievable in ASCII with existing components
- Horizontal bars (AsciiChart), vertical bars (vbar-chart), sparklines (▁▂▃▅▇), data tables
- No chart libraries needed
- Skip pie charts — use bars instead
- Tabbed view for failure analysis: summary, by-type, by-agent, by-sprint, trends

## Agreed Sprint Plan
| Sprint | Goal |
|--------|------|
| 20 | Rules in repo + README |
| 21 | Forced doc toggles + ARCHITECTURE.md |
| 22 | Test performance tab |
| 23 | Failure analysis — backend (schema + API) |
| 24 | Failure analysis — frontend (charts + views) |

---

# Memory Shape: Author-Supplied Condensed Line and Keywords

> Added 2026-10-08. Decided with Miles in session; not yet ticketed.

## Why

Context assembly renders three bands. 8-10 comes in as full text, 5-7 as one
line each, 2-4 and 1 as a bare aggregate count with a URL. The compressed band
is produced by `memory_context._one_line`, which takes the first non-blank line
of the body and truncates it at a character cap. For a lesson whose first line
is the lesson that is fine. For one that opens with setup and lands the point
three sentences in, the compressed band carries the setup and drops the lesson,
silently, and the result still looks like a summary.

The bottom two bands are worse: a count and nothing else. An agent cannot tell
what it is about to lose.

## The decision

Two new columns on `agent_memories`, both supplied by the author at write time:

- `condensed` - one line, the lesson rather than the setup. Used for the 5-7 band.
- `keywords` - two or three, used to make the 2-4 and 1 bands inspectable.

**Author-supplied, not server-derived.** A keyword extractor pulls what the text
says most often; the author knows what the lesson is for, and for a lesson the
second is the whole value. "A difference between two measurements is not a
cause" extracts as measurement / runs / truncate, which names the subject and
loses the point.

This is a quality change, not a performance one. Assembly is already
microseconds over a handful of rows. Nobody should later "optimise" it away on
the grounds that caching a truncation is cheaper.

## Sequencing, and the constraint that forces it

The columns CANNOT be `NOT NULL` at the database level until the existing rows
are backfilled, because the migration would fail against them. So:

1. Columns added NULLABLE.
2. Mandatory enforced AT THE API: a write missing either is refused 400, with
   the error naming the field, saying what it is for, and showing a correct
   body. Same pattern as `empty_body` and `tier_not_settable` - a refusal that
   teaches, living next to the code rather than in a playbook that drifts.
3. `assemble_session_context` uses stored `condensed` for 5-7. `_one_line` is
   deleted so no second path silently works.
4. Bottom bands render keywords instead of a bare count.
5. Playbooks and the server-generated `memory_usage_rules` string updated. That
   string is a second home for behaviour rules and goes stale silently; grep it
   whenever a behaviour rule changes.
6. Backfill of the existing rows: SEPARATE, LATER, its own ticket.
7. Flip the columns to `NOT NULL`: after the backfill, its own ticket.

## Open

The backfill approach is undecided: derive `condensed` for old rows from the
current truncation, or leave them legitimately blank behind a sentinel. Not to
be settled until the lane above has shipped.
