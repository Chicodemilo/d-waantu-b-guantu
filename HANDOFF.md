# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

---

## Current State

**Sprint S66 still active (id=107).** Epic 21 ("Fixing time and token tracking") in_progress. We kept S66 open today rather than closing — the work was small-ticket cleanup of the S66 backlog plus an emergent dashboard-rendering bug that pulled in real instrumentation.

**Last DWB session: id=7, opened 2026-06-10T17:07:23 via Layer-1 regex (DWB-344 UserPromptSubmit hook).** First confirmed Layer-1 open in the wild — that was the verification flagged in yesterday's handoff and it landed for free today. Closed end-of-day via ai_confident.

## Tickets shipped today (11 total)

| Ticket | Status | One-line |
|---|---|---|
| DWB-345 | done | Auto-PATCH ticket status from commit-message parse (server-side endpoint + shell hook + installer) |
| DWB-350 | done | test_dwb_session_migration teardown rebuilt via ORM-diff (auto-handles future column adds) |
| DWB-361 | done | Em-dash sweep on agent_memory.py identity template (16 instances + test assertion update) |
| DWB-365 | done | project_agents bridge invariant enforced at agent-create + delete_agent FK landmine fixed |
| DWB-366 | done | deploy-playbooks scaffolds root INITIAL/ARCHITECTURE/HANDOFF skeletons |
| DWB-370 | done | Project page blank-screen on click (AbortController + .catch + ErrorBoundary at AppShell) |
| DWB-371 | done | Frontend client log feed to backend — client_logs table + endpoints + frontend logger + instrumentation |
| DWB-372 | done | Backend application log via API — ring buffer + custom logging.Handler + /api/server-logs |
| DWB-374 | done | App remount root cause: SessionFooter conditional useMatch via `||` violated Rules of Hooks |
| DWB-375 | done | Favicon: D'B monogram in GOB Bluth color order (green-orange-blue) |
| Cross | -- | All 5 original S66-backlog tickets cleared (361, 350, 366, 365, 345); 6 emergent (370/371/372/374/375 + diagnostic work) |

## Open backlog (S66)

| Ticket | Notes |
|---|---|
| DWB-373 | Sessions table tix_done column always 0 — aggregator bug. Tokens column likely same root cause. Backlog. |

## The big story — DWB-374 / SessionFooter

The dashboard blank-screen symptom started as DWB-370 (click project link → blank). Freddie shipped a layered fix: AbortController + .catch + ErrorBoundary at AppShell + the `lastPolled` gate on ProjectPage. That improved the refresh case but did NOT fix the click case. Symptom kept reproducing.

We were guessing because there was no diagnostic surface. So we filed and shipped DWB-371 + DWB-372 to get logger feeds (frontend + backend) into the backend store, queryable via curl. The investment paid for itself immediately.

The diagnostic arc:
1. `store.hydrated` fired 12 times in 5 min of normal navigation → useAppData remounting → App.jsx remounting on every SPA nav.
2. Instance counter probe (`APP_INSTANCE_COUNTER` module var + `useRef`) → instance number stayed at #2 across all nav. So same React instance was firing mount→unmount→mount repeatedly. Weird.
3. Boundary-cross identification: app.lifecycle events only fired when crossing project↔top-level. Intra-project nav was clean.
4. Triad probe (window.error listener + RootErrorBoundary above App + RootProbe above BrowserRouter) caught the actual throw with full componentStack.
5. **Root cause: `SessionFooter.jsx:84` had `useMatch('/projects/:id/*') || useMatch('/projects/:id')`** — second useMatch called CONDITIONALLY. Hook count changed across the project↔top-level boundary. React's `areHookInputsEqual` tried to compare a stale undefined deps array to a new one, `.length` threw, the throw propagated past App (ErrorBoundary was inside AppShell, below the throw site), React tore down the entire tree.
6. Fix: single `useMatch('/projects/:id/*')`. Splat matches zero or more segments, so it covers both `/projects/7` and `/projects/7/tickets`.

One-line fix after ~10 layers of instrumentation. The DWB-371 + DWB-372 logger infrastructure was the unlock — without backend-readable client logs we'd still be guessing.

## Lessons captured today

1. **DWB-371 + DWB-372 are the diagnostic substrate.** Browser-console-only debugging is dead for this project. When something blanks, curl `/api/client-logs?level=error` and `/api/server-logs?level=error` first.
2. **Rules-of-Hooks violations show up as `Cannot read properties of undefined (reading 'length')` from `areHookInputsEqual`** when crossing render shapes. If you see that throw with a `useMemo`/`useEffect`/`useCallback` stack, look for conditional hook calls (`||`, `&&`, early-return-then-hook).
3. **`client_logs.occurred_at` uses `sa.DateTime()` — no fractional seconds in MySQL.** Same-second events sort randomly. Use `id` (auto-increment) for true write order until DWB-376 (when we file it) fixes precision.
4. **Diagnostic ordering: backend-only via DB id is more reliable than client-side `occurred_at` until the precision fix lands.**
5. **DWB-365 delete_agent FK landmine:** when you add a child relationship (project_agents bridge insert on agent create), the matching delete needs an explicit pre-delete OR ON DELETE CASCADE. SQLA defaults to NULLing the FK which violates NOT NULL.
6. **Server-side parse > shell-side parse for hook integrations** (DWB-345). Keep the shell as a thin curl, push all logic to a Python endpoint. Easier to test, single audit point, no env-var setup cliff per clone.
7. **Skip-ceremony only when user signals it** — kept enforcing this today. Bug fixes that aren't trivially scoped still go through tickets.
8. **TIX DONE column in sessions table is broken** (DWB-373) — aggregator doesn't count done-transitions in the session window. Cosmetic but noticed.
9. **Workers cannot Edit/Write any path under `.claude/`** — still the hard rule. All memory writes go through `POST /api/agents/{id}/memory/append` or `/session-complete`. Today all three workers (Barry, Freddie, Sylvie) wrote notes cleanly via that path. Zero crashes.

## Plan for next session

1. **DWB-373** — tix_done aggregator. Probe status_history transitions within session window first, then fix the aggregator. Likely 30-min ticket.
2. **DWB-376 (TO FILE)** — `client_logs.occurred_at` precision. Migrate to `DateTime(fsp=3)` for millisecond ordering. Small.
3. **DWB-377 (TO FILE)** — Dashboard fetch fan-out: 16+ parallel `getTrackingSummary` calls on dashboard mount. CrossProjectSummary + TimeTokens + 4 ProjectCards each map over projects independently. Deduplicate via shared cache hook.
4. **IDEAS.md backlog** (in repo root) — 9 design ideas captured, ranked into tiers. Pick from Tier 1 (#3 session info on project headers, #1 team status cleanup) when bandwidth opens.
5. **Sage reactivated today** (id=6, project 1). She's on the roster again — use for next sprint's testing work.
6. **GHK1 (project id=11) deleted** — was a leftover smoke-test artifact from Barry's DWB-345 verification. Cleaned up mid-session.

## Team status at session close

| Agent | Role | State |
|---|---|---|
| Archie_DWB (13) | TL | Active (you, on next spawn) |
| Barry_DWB (21) | Backend | Alive — wrote session notes via session-complete |
| Freddie (19) | Frontend | Alive — wrote session notes after DWB-374 ship |
| Sylvie (27) | System-ops | Alive — wrote session notes |
| Sage (6) | Tester | Reactivated mid-session, no work assigned yet |
| Pam_DWB (14) | PM | Not spawned today (small team mode, TL drove) |
| Dolores (28) | Docs | Not spawned (still recovering from yesterday's `.claude/` crash class) |

## Gotchas (carry forward)

- **`.claude/` Edit by subagent = crash.** Hard rule (unchanged from yesterday).
- **Rules of Hooks violations cascade to whole-tree teardown** if no error boundary above the throw site. ErrorBoundary inside AppShell is below App; a throw in a layout component sibling of AppShell propagates past it. Consider whether the inner ErrorBoundary should hoist.
- **client_logs DateTime precision** (above).
- **Customfield IDs vary per Jira instance.** Probe payloads first.
- **`SendMessage` is name-literal.** Verify suffix on respawned teammates.
- **Marker sweeper runs every 10 min** with 30-min stale threshold.
- **GET /api/projects/{id}/sessions does NOT accept a `status` query param.** Filter client-side.
- **`app/config/` is a package now.**
- **`participants_for_sprint` counts TL admin acks** (DWB-329 backlog).
- **Vite Fast Refresh module-state behavior:** module-level `let` variables persist across HMR updates of the same module, but `useRef` returns new objects on full component remount. The instance-counter probe relied on this — useful diagnostic tool.

## Test counts at close

- **Backend: 991 passing** (931 baseline + 21 from S66 cleanup + 16 client_logs + 23 server_logs)
- **Frontend: ~92 passing** (24 pre-existing failures from `__tests__/api/*` mock + JiraIssuesPage date-pad, unrelated)

## Session-end notes (2026-06-10 PM)

Big day. 11 tickets shipped, the diagnostic infrastructure that's now permanent in the codebase, and the root cause of a multi-day blank-screen ghost finally pinned to a single conditional `||` in SessionFooter. The hunt took ~10 instrumentation iterations but every one yielded a clean next step — which is what good diagnostic surfaces are for. DWB-371 + DWB-372 paid for themselves on their first real use case.

Team parked alive. Sage back on the roster.
