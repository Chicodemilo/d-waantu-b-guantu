# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

---

## Current State

**Sprint S66 active (id=107).** Epic 21 ("Fixing time and token tracking") in_progress. S66 main thrust SHIPPED on the backend (335/336/337/338). 331/332/333 cleanup also shipped. Frontend (339) and docs (340) NOT done. Sprint not yet closed.

11 commits pushed today: 4c212f2..59751b0.

### S66 ticket state at session end

| Ticket | Status | Notes |
|---|---|---|
| DWB-331 | done | Single in_progress epic + single active sprint, DB enforced via generated col + UNIQUE |
| DWB-332 | done | jira_enabled on identify + 400 gate on jira_issue_key + deploy-playbooks scrub markers |
| DWB-333 | done | PATCH ticket sprint_id=null returns 400 not 500 |
| DWB-334 | in_review | Progress bar gradient height/padding; visual eyeball still pending from user |
| DWB-335 | done | dwb_sessions schema + migration + single-active UNIQUE + FK on hook_sessions |
| DWB-336 | done | SessionStart/End regex phrase detection + POST /api/sessions/open + close endpoints |
| DWB-337 | done | Idle-timeout sweeper (asyncio, 60min default, env-configurable) |
| DWB-338 | done | GET list + GET detail with by_role, by_ticket, overhead, live flag |
| DWB-339 | todo | Dashboard panel: Current Session + Recent Sessions. Freddie's, not picked up. |
| DWB-340 | todo | User-facing lifecycle docs. Dolores's, agent not spawned this session. |
| DWB-341 | backlog | Auto-scaffold agent memory dirs on POST /api/agents + spawn-prepare. Filed mid-session. |
| DWB-342 | todo | Jira unification: synced ticket table + fuzzy search + sortable. Big follow-on, multi-subtask. |

### Live state of DWB sessions on project 1

Two `dwb_sessions` rows exist (id=2, id=3), both closed with 0 tokens. Both are smoke-test artifacts from Sylvie/Barry during DWB-336/338 development. **No real DWB session has bounded actual work yet.** This session (the one writing this handoff) was opened before the regex layer deployed, so it was never auto-opened.

## Plan for the next session

User wants to test the lifecycle end-to-end. Expected flow:

1. Open new CC session.
2. Type the open phrase: "you are archie, read the playbook" (or any variant from `app/config/session_phrases.py` OPEN_SOURCES).
3. SessionStart hook should match via Layer 1 regex and POST /api/sessions/open with `open_method="regex"`. New session id returned.
4. Work happens. Hook_sessions for spawned workers get linked to the active DWB session at ingestion time.
5. Close phrase ("have the team write docs and exit", "close this session", etc.) triggers SessionEnd hook → POST /api/sessions/{id}/close.
6. Or: 60min idle → sweeper auto-closes with `close_method="idle_timeout"`.

If the regex hook DOESN'T fire on open, fall back to Layer 2 (TL AI reasoning per team_lead_playbook § 4e): explicitly POST /api/sessions/open with `open_method="ai_confident"` after recognizing the intent.

Verify via:
```
curl http://localhost:8000/api/projects/1/sessions
```

## Active Decisions

- **Passive session model is now built.** Source-of-truth doc lives at team_lead_playbook § 4e. Phrase catalogue at `backend/app/config/session_phrases.py` (editable single-file).
- **Single in_progress epic + single active sprint per project** is now DB-enforced (DWB-331). Trying to create or transition a second returns 409 with the conflict row in the body.
- **Non-Jira projects** are now visible and gated (DWB-332). `jira_enabled` exposed on identify. POST/PATCH ticket refuses `jira_issue_key` writes when `jira_base_url` is null. Deploy-playbooks scrubs Jira sections via HTML-comment markers (`<!-- jira-only:start/end -->`).
- **PATCH ticket sprint_id=null returns 400** with a friendly body pointing at the reassign workflow. Sibling FKs (epic_id, assigned_agent_id) ARE nullable; that's fine.
- **Playbooks audited and cleaned.** 16 fixes landed in commit 59751b0 covering stale wording (DWB-331 enforcement, missing session endpoints), Jira/non-Jira scoping, threshold orthogonality framing, PM/TL role-split clarification on sprint close, identify response shape drift, DWB vs Jira key distinction, and a full em-dash sweep (0 em dashes across all three playbooks).
- **No icons, no em dashes** rule is now self-consistent across worker, TL, and PM playbooks.

## Carry-over from Archie_CI (deferred to user/CI side)

`PATCH /api/projects/5` to set `jira_base_url=https://roadvantage.atlassian.net` + `jira_project_key=POR`. Then backfill `jira_issue_key` on the 9 orphan CI tickets (CI-402..CI-410). DWB-332's gate is doing exactly what it should; the fix is on the CI project config side. Message drafted for Archie_CI in this conversation, user to forward.

D2J `--continue-on-link-fail` flag is a cross-repo follow-up (lives in D2J, not DWB).

## Backlog after S66

- **DWB-339** — Dashboard panel (frontend, Freddie). Cannot SEE the session data on the dashboard until this lands.
- **DWB-340** — Lifecycle docs (Dolores). Next session should land this.
- **DWB-341** — Auto-scaffold agent dirs. Cross-project ergonomics fix; FRAUDI hit the gap.
- **DWB-342** — Jira unification (synced table + fuzzy search + sortable). Multi-subtask, big.
- **DWB-329** — Refine `participants_for_sprint` to exclude TL admin acks.
- Open-session live view tweaks (heartbeat hook for TL tokens) — deferred per user "we'll fuck with the live view next."
- D2J side: `--continue-on-link-fail` flag (Archie_CI ask).
- Optional follow-up: TicketUpdate.sprint_id schema tightening (omit-only). Defer to ride DWB-342.

## Gotchas (carry forward)

- Alembic autogenerate misses MySQL enums + generated columns. Always hand-write migrations touching either.
- Stale `.pyc` cache can mask real test failures. `find backend -name __pycache__ -exec rm -rf {} +` before pytest counts after fixture changes.
- `app/config/` is a package now (DWB-336 introduced session_phrases.py there). The standalone `app/config.py` was retired and Settings moved into `app/config/__init__.py`. Both `from app.config import settings` and `from app.config.session_phrases import ...` work.
- `agent_type` in SubagentStop payload is empty string in practice.
- `participants_for_sprint` counts TL admin acks (DWB-329 backlog).
- GET /api/projects/{id}/sessions does NOT accept a `status` query param. Filter client-side for `closed_at IS NULL` until DWB-339 or a follow-up tightens it.

## Test status

**743 backend tests passing** after DWB-331 land (plus ~7 more from DWB-333 = 750, plus 14 from DWB-332 = 764). Last verified count is 764 on full suite, clean .pyc, all green.

## Session-end notes (2026-06-09)

- Opened with "you are archie, you are team lead, read the playbook" but the regex layer hadn't deployed yet — no DWB session was auto-opened for THIS conversation. The two existing sessions on project 1 are smoke-test rows only.
- Closed with "Lets close this session and try again see what we do." Recorded as confident close intent but no active session to close.
- Team spawned this session: Pam_DWB, Freddie, Barry_DWB, Sylvie. All idled cleanly. Will stop when this CC session ends.
- Next session: open with the same phrase ("you are archie, read the playbook") and verify the SessionStart hook actually fires the regex layer + opens a session this time.
