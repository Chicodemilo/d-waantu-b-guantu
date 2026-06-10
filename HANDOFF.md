# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

---

## Current State

**Sprint S66 active (id=107).** Epic 21 ("Fixing time and token tracking") in_progress. Backend complete on the regex layer. Frontend (DWB-339) and docs (DWB-340) still open. Sprint not yet closed.

12 commits pushed prior session + 1 new today: 6f01ccd.

### S66 ticket state at session end

| Ticket | Status | Notes |
|---|---|---|
| DWB-331 | done | Single in_progress epic + single active sprint, DB enforced |
| DWB-332 | done | jira_enabled on identify + 400 gate + deploy-playbooks scrub markers |
| DWB-333 | done | PATCH ticket sprint_id=null returns 400 not 500 |
| DWB-334 | done | Progress bar gradient height/padding (closed this session) |
| DWB-335 | done | dwb_sessions schema + migration + single-active UNIQUE + FK |
| DWB-336 | done | SessionStart/End regex phrase detection + POST /api/sessions endpoints |
| DWB-337 | done | Idle-timeout sweeper (asyncio, 60min default) |
| DWB-338 | done | GET list + GET detail with by_role, by_ticket, overhead, live |
| DWB-339 | todo | **NEXT SESSION FOCUS** — Dashboard panel: Current Session + Recent Sessions. Freddie. |
| DWB-340 | todo | User-facing lifecycle docs. Dolores. User asked to "write all our docs when we get back." |
| DWB-341 | backlog | Auto-scaffold agent memory dirs on POST /api/agents + spawn-prepare |
| DWB-342 | todo | Jira unification (synced table + fuzzy search + sortable). Multi-subtask. |
| DWB-343 | done | **THIS SESSION** — SessionEnd retry for OPEN regex. Barry shipped, 4 tests. |
| DWB-344 | done | **THIS SESSION** — UserPromptSubmit hook for instant open detection. Sylvie wrote impl, Barry wrote tests, TL wired settings.json. 4 tests. |

### DWB sessions state

dwb_sessions: id=4 opened this session at 17:20:15 via `ai_confident` (Layer 2 fallback after the regex hook missed). Will close on session end.

### Layer-1 regex root-cause + fix (this session's main work)

Layer-1 regex layer (DWB-336) missed the open phrase on SessionStart because CC writes the SessionStart hook ~2 seconds BEFORE the user's first message hits the transcript JSONL. Confirmed empirically by inspecting hook_session id=355 vs transcript b1230b96...jsonl line 3 (user "you are archie, read the playbook" at 17:19:37.663Z vs SessionStart at 17:19:35).

Two fixes shipped in commit 6f01ccd:
- **DWB-343 (retry path):** handle_session_end now also calls try_open_dwb_session_from_transcript. Any subsequent Stop/SessionEnd/SubagentStop catches the open. ~3 LOC + 4 tests.
- **DWB-344 (fast path):** New POST /api/hooks/user-prompt endpoint + handle_user_prompt service. CC's UserPromptSubmit hook fires with the prompt text in the payload, so we match the open regex directly without transcript scan. Tolerant: noops on missing prompt, bad cwd, no match, or already-open. Endpoint always returns HTTP 200. settings.json wired with the UserPromptSubmit hook block. ~80 LOC + 4 tests.

**Verification for next session:** Open a fresh CC session with "you are archie, read the playbook". The UserPromptSubmit hook (DWB-344) should open a regex-method DWB session BEFORE Archie's first response completes. Verify via `curl http://localhost:8000/api/projects/1/sessions` and look for `open_method=regex` on the latest row.

## Critical lesson learned this session

**Subagents cannot edit `.claude/settings.json` (or other harness-config files).** The CC tri-option permission dialog ("Yes / Yes-and-allow / No") crashes subagent processes inside the ink terminal renderer. Three casualties this session: Sylvie, Sylvie-2 (both at the same settings.json Edit), and Pam (trigger unclear, possibly something different — investigation pending).

**Workaround:** TL handles all `.claude/settings.json` edits directly. This is a hard exception to "TL never codes." Workers can safely write to their own `.claude/agents/memory/<prefix>/<agent>/` paths (those are their designated place) and to all non-`.claude/` project code.

Memory saved at `~/.claude/projects/.../memory/feedback_teammate_writes_can_crash.md`.

## Plan for the next session

User signal: "write all our docs when we get back... front end on session tracking."

1. Open fresh CC session with "you are archie, read the playbook". **Verify the regex layer (DWB-344) now fires correctly** — should see a regex-method DWB session opened before Archie's first response.
2. Frontend focus: **DWB-339** (Dashboard panel — Current Session + Recent Sessions). Spawn Freddie. Read DWB-338 endpoint shape for the data contract.
3. Docs focus: **DWB-340** (User-facing session lifecycle docs). Spawn Dolores.
4. After both ship: close S66, run sprint hygiene, open S67.

## Active Decisions (cumulative)

- Passive session model: Source-of-truth doc at team_lead_playbook § 4e. Phrase catalogue at `backend/app/config/session_phrases.py`.
- Single in_progress epic + single active sprint per project, DB-enforced (DWB-331).
- Non-Jira projects visible and gated (DWB-332). DWB itself is non-Jira.
- PATCH ticket sprint_id=null returns 400 (DWB-333).
- Layer-1 OPEN regex now has both a retry path (DWB-343, on session-end hooks) and a fast path (DWB-344, on UserPromptSubmit). SessionStart no longer the only entry point.

## Carry-over to other projects

`PATCH /api/projects/5` for CI: set `jira_base_url=https://roadvantage.atlassian.net` + `jira_project_key=POR`. Then backfill `jira_issue_key` on the 9 orphan CI tickets (CI-402..CI-410). Message drafted for Archie_CI in the prior session, user to forward.

D2J `--continue-on-link-fail` flag still a cross-repo follow-up.

## Backlog after S66

- **DWB-339** — Dashboard panel (frontend, Freddie). **Next-session primary.**
- **DWB-340** — Lifecycle docs (Dolores). **Next-session primary.**
- **DWB-341** — Auto-scaffold agent dirs. FRAUDI hit the gap.
- **DWB-342** — Jira unification. Multi-subtask, big.
- **DWB-329** — Refine `participants_for_sprint` to exclude TL admin acks.
- Open-session live view tweaks (heartbeat hook for TL tokens).
- D2J side: `--continue-on-link-fail` flag.

## Gotchas (carry forward)

- **NEW: Subagents die on `.claude/settings.json` edits.** TL handles those directly. See "Critical lesson" above.
- Alembic autogenerate misses MySQL enums + generated columns. Hand-write migrations.
- Stale `.pyc` cache can mask real test failures. `find backend -name __pycache__ -exec rm -rf {} +` before pytest after fixture changes.
- `app/config/` is a package (DWB-336). Both `from app.config import settings` and `from app.config.session_phrases import ...` work.
- `agent_type` in SubagentStop payload is empty string in practice.
- `participants_for_sprint` counts TL admin acks (DWB-329 backlog).
- GET /api/projects/{id}/sessions does NOT accept a `status` query param. Filter client-side for `closed_at IS NULL`.

## Test status

**772 backend tests passing** after this session's adds (+8 from DWB-343/344). Last verified count is 772 on full suite, clean .pyc, all green.

## Session-end notes (2026-06-09, second session of the day)

- Layer-2 ai_confident OPEN worked correctly (dwb_sessions id=4). Regex layer missed for the documented reason.
- Three teammate casualties to the protected-file crash pattern. Mitigation in place going forward.
- Pam_DWB-2 alive at session end (respawned after Pam's death). Sylvie permanently absent (Sylvie-2 also dead, user closed both team-config entries).
- Team will shut down on close.
