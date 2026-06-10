# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

---

## Current State

**Sprint S66 active (id=107).** Epic 21 ("Fixing time and token tracking") in_progress.

**Last DWB session: id=5, closed 2026-06-10T16:59:59 via `ai_confident`** with headline "S66 close: session-tracking arc + Jira unification + worker memory fix". Layer-1 regex (DWB-343/344) did not fire on open — opened via Layer 2 at 11:55 because the canonical phrase wasn't typed. Worth a verification next session.

**Last commit:** `40887a1` — pushed to master. 94 files in one bundle covering ~25 shipped tickets.

### S66 tickets shipped today (in commit 40887a1)

| Ticket | Status | One-line |
|---|---|---|
| DWB-339 | done | SessionPanel live view |
| DWB-340 | done | docs/session_lifecycle.md user-facing reference |
| DWB-341 | done | Auto-scaffold agent memory dirs on POST /api/agents + spawn-prepare |
| DWB-342 | done | Unified Jira page (single nav, 13-col table, fuzzy search, sortable, manual sync, read-only) |
| DWB-343 | done | SessionEnd OPEN regex retry (catches the SessionStart-before-transcript race) |
| DWB-344 | done | UserPromptSubmit hook for instant open-phrase detection |
| DWB-346 | done | Sessions list aggregates + headline column |
| DWB-347 | done | Sessions page + nav `sessions` link + phrase-help block |
| DWB-348 | done | Session detail page at /projects/:pid/sessions/:sid |
| DWB-349 | done | SessionFooter unified (5 dot states, merged with polling footer) |
| DWB-351 | done | Privacy: AI-layer phrase fields forced NULL, UserPromptSubmit prompt scrubbed |
| DWB-352 | done | memory_usage_rules inline on identify + spawn-prepare |
| DWB-353 | done | Ad Hoc overhead bucket + dead-alert removal (unattributed + tokens-not-reported) |
| DWB-354 | done | Ad Hoc UI row + tooltip |
| DWB-355 | done | Playbook audit folding in S66 changes |
| DWB-356 | done | Jira normalizer: sprint name (env-overridable customfield) + reporter |
| DWB-357 | done | Parent: fix worker memory-write crash (umbrella) |
| DWB-358 | done | POST /api/agents/{id}/memory/append (safe server-side writes) |
| DWB-359 | done | Worker playbook scrub of deadly direct-write guidance |
| DWB-360 | done | E2E verify memory-append (Barry self-test was the empirical proof) |
| DWB-362 | done | Jira table type column |
| DWB-363 | done | Jira table epic column (key + name via batched lookup) |
| DWB-364 | done | Jira table parent column (gated on issuetype.subtask) |
| DWB-367 | done | Agent .md files: rewrite docs/ refs to .claude/ |
| DWB-368 | done | Playbook prose cross-refs + AUX_DOCS deploy manifest extension |
| DWB-369 | done | marker_sweeper periodic task (pending-* GC + finalized cleanup) |

### Cross-project shipped today (D2J)

| Ticket | Status | One-line |
|---|---|---|
| D2J-19 | done | dwb2jira create sprint membership via customfield PUT (not legacy agile POST) |
| D2J-20 | done | dwb2jira report --sprint via JQL on customfield (not agile sprint-issue endpoint) |

Shipped to `/Users/mchick/Dev/DWB_2_JIRA/` by Barry_DWB as cross-project assist (he had the Jira-sync context from same-day DWB work). D2J's HANDOFF.md updated with the heads-up for the eventual Archie_D2J spawn. `JIRA_SPRINT_CUSTOMFIELD=customfield_10021` set in D2J's `.env`.

### Open backlog filed during the arc

| Ticket | Notes |
|---|---|
| DWB-345 | Auto-PATCH ticket status=done via commit-message parse |
| DWB-350 | test_dwb_session_migration teardown leaves schema missing post-335 cols |
| DWB-361 | Em-dash sweep on agent_memory.py identity template |
| DWB-365 | Enforce project_agents bridge invariant on agent creation |
| DWB-366 | deploy-playbooks: also scaffold root INITIAL/ARCH/HANDOFF skeletons |

All five are filed and prioritized as backlog — none blocking.

## Key lessons captured today

These also live in `~/.claude/projects/.../memory/feedback_*.md` and the worker / TL playbooks via DWB-355 + DWB-359:

1. **Subagents cannot Edit/Write/NotebookEdit ANY path under `.claude/`.** The CC permission dialog crashes them in the ink renderer. Casualties this session: Sylvie, Sylvie-2, Pam, Freddie, Dolores. Hard checklist: grep ticket scope for `.claude/` paths before assigning to a subagent. If hit, TL handles directly.
2. **DWB-358 memory-append endpoint is the canonical in-flight memory write path** for workers. Direct Edit of memory files crashes them; the server-side endpoint bypasses the dialog.
3. **`SendMessage` routes by literal teammate name.** After a respawn, `Pam_DWB` -> `Pam_DWB-2`. Addressing the original name silently drops the message into a dead inbox. Verify via `GET /api/projects/{id}/team` before sending.
4. **Probe-first against real data before coding.** DWB-356 customfield ID (10020 default vs 10021 Roadvantage), D2J-19 spec inaccuracy, D2J-20 reproduction status all caught by direct Jira-payload inspection. Saved at least one wasted ship cycle.
5. **Migration discipline: `alembic upgrade head` + re-sync FRAUDI + SQL spot-check BEFORE flipping in_review** on any schema-touching ticket. The DWB-362 migration gap 500'd every sync until manually applied. Now standard practice per Barry.
6. **Read-only Jira contract enforced via `FakeReadOnlyJira` whitelist** in tests. Mock client refuses any non-whitelisted method, so future regression adding a write call fails loud.
7. **Cross-project debugging works.** Archie_CI surfaced 5 systemic findings today; all five closed by end of day.

## Plan for the next session

1. **Verify Layer-1 regex actually fires on open** — open a fresh CC session with the canonical phrase `you are archie, read the playbook`. Footer should turn active before Archie's first response completes. `open_method=regex` on the new dwb_session row. This was the verification HANDOFF flagged from S66 day 1 and we still haven't seen Layer 1 catch a real open.
2. **DWB-366**: extend deploy-playbooks to scaffold root INITIAL/ARCH/HANDOFF skeletons. Half done already (the .claude/-side scaffold landed); just need the root-doc skeletons added to the manifest.
3. **DWB-345**: auto-PATCH ticket status on commit-message parse. Closes the last manual housekeeping step in the workflow.
4. **DWB-365**: enforce project_agents bridge invariant. The FRAUDI drift today (3 missing links) was a one-off backfill; the underlying cause needs a service-level guarantee.
5. **DWB-350/361** are tiny tech-debt items; can ride alongside any sprint.

## Team status at session close

| Agent | Role | State |
|---|---|---|
| Archie_DWB (13) | TL | Active |
| Pam_DWB-2 (14) | PM | Alive at close — write-up requested via session-complete |
| Barry_DWB (21) | Backend | Alive — write-up requested |
| Freddie (19) | Frontend | Alive — write-up requested |
| Sage (6) | Tester | Alive — write-up requested |
| Dolores (28) | Docs | Dead (crashed on DWB-367 protected-file Edit, not respawning) |

5 casualties total this session — all `.claude/` protected-file crashes. Memory rule strengthened so future spawns inherit the awareness via memory_usage_rules + the hardened worker playbook.

## Gotchas (carry forward)

- **`.claude/` Edit by subagent = crash.** Hard rule.
- **Alembic upgrade ALWAYS before in_review** on schema-touching tickets.
- **Customfield IDs vary per Jira instance.** Probe real payloads; make IDs env-overridable.
- **`SendMessage` is name-literal.** Verify suffix on respawned teammates.
- **Marker sweeper runs every 10 min** with 30-min stale threshold. If marker dirs look stale, the sweeper's likely off or the env vars need tuning.
- **GET /api/projects/{id}/sessions does NOT accept a `status` query param.** Filter client-side.
- **`app/config/` is a package now.** Both `from app.config import settings` and submodule imports work.
- **`participants_for_sprint` counts TL admin acks** (DWB-329 backlog).

## Test count

**931 backend tests passing** on the DWB suite. **152 D2J tests passing** post D2J-19/20.

## Session-end notes (2026-06-10)

Heavy day. ~25 DWB tickets + 2 D2J tickets shipped, 1 mega-commit pushed, Archie_CI cross-project audit fully closed end-to-end. The worker memory-write fix (DWB-357 arc) is the structural unblock — workers can now record their own lessons without dying. Five casualties on the protected-file crash class — all documented, all rule-bound. Team parked alive for tomorrow.
