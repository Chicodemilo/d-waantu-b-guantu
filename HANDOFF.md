# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (as of 2026-06-25)

- Backend 1482 passing / 0 fail, frontend 252 passing / 0 fail. DWB session 47 still OPEN (this session active).
- Three sprints shipped + closed this session: S73 (help center), S74 (reliable session write-ups), S75 (help-center polish). All on epic 40 + earlier.
- Team LIVE (Pam_DWB, Freddie, Sylvie, Barry_DWB, Sage) and parked - NOT shut down. Respawn + verify live names if a later session inherits this.
- S73 was committed+pushed earlier (82351a8). S74 + S75 committed together this session (see git log); pulled an externally-merged PR before pushing.

## Shipped this session

**S73 - In-app Help Center** (`/help`): quick-start (flow + standalone callouts) + 12 domain sections mirroring the nav, each Why/How/Where + bullets. Reusable `FuzzySearch`/`useFuzzyFilter`, `CollapsibleSection`, `SummaryHeader`; content auto-discovered from `helpContent/sections/*.js` via `import.meta.glob` (see `helpContent/CONTRACT.md`). All 7 slash commands documented in-place.

**S74 - Reliable Session Write-ups + keyword substrate**:
- Deterministic synthesizer (`session_synthesizer.py`, NO LLM) runs in `_apply_synthesis` inside `close_session` on EVERY close path + the idle sweeper (which routes through close_session). Produces: headline (kept if supplied, else synthesized ~5-10 words - fixes the null-headline bug on idle/regex closes), structured `summary` JSON `{lead, sections:[{title,bullets}]}` on `dwb_sessions.summary`, and weighted keywords.
- Keywords: `keyword_extraction.py` (pure: frequency rank + stopword drop, ticket keys verbatim, kebab-case) over an agent-text-only corpus (`_gather_corpus`, no user prompts - DWB-351), stored in the generic `entity_keywords` table (entity_type/entity_id/keyword/weight, both indexed) = substrate for FUTURE cross-entity linked relations (NOT built yet; v1 weight is plain TF, schema leaves room for TF-IDF).
- Read API (list + detail) exposes summary + keywords, one batched query. Synthesis guarded (never blocks a close) + idempotent on reopen. A one-shot backfill (`scripts/backfill_session_synthesis.py`) populated legacy null-headline sessions 32/36/38.

**S75 - Help-center polish**: quick-start wrapped in a CollapsibleSection (default OPEN); in-help cross-link mechanism (section-level `links: [{to, label}]`, `to` = section key, renders a "See also" row, force-opens + smooth-scrolls the target, graceful-skip on bad targets); 25 broad-brush cross-references authored across the 12 sections; link-integrity test guards targets.

## Backlog (parked, out of active workstream)
- DWB-492: ticket_key query filter returns non-exact row (cross-ticket-PATCH hazard). Low.
- DWB-494: DONE this session (corpus dual-path consolidated to `_gather_corpus`).

## Gotchas (carry forward)
- **ARCHITECTURE.md ceiling raised 7500 -> 8500** (DWB-490, token_budget.py + its test) - the doc legitimately grew; it now sits ~7755/8500.
- **The corpus dedup caused a brief backend outage** mid-session: deleting `session_keywords.py` while `dwb_session.py` still imported it crashed the import. Lesson: verify ALL callers before deleting a module; don't dedup live under concurrent edits. Resolved clean (`_gather_corpus` canonical, `session_keywords.py` gone).
- **Teammate message BODIES sometimes don't reach the TL** (only the summary line) - ask workers to put key facts in a one-line summary; and message timing CROSSES often (a stand-down crossed a worker's already-finished work - verify timing before concluding).
- helpContent uses `import.meta.glob` auto-discovery + the documented CONTRACT (sections + cross-link `links`); add `sections/<key>.js`, no wiring.
- `.claude/` edits crash subagents; root `.md` + `frontend/src` + backend are safe for workers.
