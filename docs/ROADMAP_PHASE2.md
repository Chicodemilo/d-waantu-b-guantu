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
