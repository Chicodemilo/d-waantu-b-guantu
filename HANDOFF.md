# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current State (end of 2026-06-25, session 53)

- Working tree committed + pushed to origin/master (this wrap batch + an earlier 46da1a5 that also merged an external fresh-install-migration PR). Backend 1482 passing, frontend 255 passing.
- Sprints this session, all closed: S72 (alerts-vs-actions), S73 (help center), S74 (reliable session write-ups + keyword substrate), S75 (help polish), S76 (keyword tuning). Epics 37 + 40.
- DWB session 47 = the big build session (closed, has a synthesized write-up). DWB session 53 = keyword-tuning + wrap (closed at end of this session via explicit TL close).
- **Team shut down at end of session 53** (Pam_DWB, Freddie, Sylvie, Barry_DWB, Sage, Dolores all terminated). RESPAWN before use next session: spawn-prepare + pending marker + Agent tool per `.claude/` team playbook; verify live names; do NOT SendMessage cold roster names.

## Shipped this session

- **S73 Help Center** (`/help`): quick-start (flow + standalone callouts) + 12 nav-mirroring domain sections (Why/How/Where + bullets), live fuzzy search. Reusable `FuzzySearch`/`useFuzzyFilter`, `CollapsibleSection`, `SummaryHeader`. Content auto-discovered from `frontend/src/helpContent/sections/*.js` via `import.meta.glob` (see `helpContent/CONTRACT.md`).
- **S74 Session write-ups + keyword substrate**: deterministic synthesizer (`session_synthesizer.py`, NO LLM) runs in `_apply_synthesis` inside `close_session` on EVERY close path + idle sweeper -> headline (synth when none supplied; kills the null-headline bug), structured `summary` JSON, weighted keywords. Keywords via `keyword_extraction.py` (pure) over a prose-only corpus (`_gather_corpus`, no user text). Stored in the generic `entity_keywords` table (entity_type/entity_id/keyword/weight, both indexed) = substrate for FUTURE cross-entity linked relations.
- **S75 Help polish**: quick-start wrapped collapsible (default open); in-help cross-links `{to, label}` (force-open + scroll a section); portal links `{route, label}` (SPA-nav to the 5 global pages); link-integrity test.
- **S76 Keyword tuning**: DWB-499 stopword cleanup (number-words/filler; NO domain terms); DWB-500 TF-IDF down-weighting (IDF over the FULL session corpus, computed in the DB/backfill layer; `entity_keywords.weight` is now a TF-IDF relevance score, not a raw count). Result: per-session tags now diverge by topic. Backfilled ALL null-headline closed sessions + the 2 recent headlined ones (42/40, write-ups+tags only, headlines kept).
- Docs: ARCHITECTURE updated (DWB-490, ceiling raised 7500->8500). QUICKSTART + FILE_TREE (S73). Playbooks: team_lead (close auto-synth + idle-timeout 60min->10h fix), worker (Shared Code: grep callers before deleting). Slash-command script timeouts bumped 2-3s -> 10s.

## Backlog (parked, OUT of active workstream, excluded from gates)
- DWB-492: `ticket_key` query filter returns non-exact row (cross-ticket-PATCH hazard). Low.
- DWB-494: DONE this session (corpus dual-path consolidated to `_gather_corpus`).
- DWB-502: project-scoped help portal links pending a no-project fallback (global ones shipped).
- DWB-503: TF-IDF df perf — corpus-wide df is recomputed per close (sweeper-amplified, O(N x corpus)); fine at ~40 sessions, won't scale. Fix: per-sweep cache or incremental/persistent df table. NOT blocking.

## Gotchas (carry forward)
- **DEDUP CAUSED A LIVE OUTAGE**: deleting `session_keywords.py` while `dwb_session.py` still imported it crashed the API. Grep ALL callers before deleting shared code; never dedup a hot shared file (esp. `dwb_session.py`, the close path) live under concurrent edits. (Now in worker_playbook.)
- **Message timing crosses constantly** + teammate message BODIES often don't reach the TL (only the summary). Verify timing before concluding a teammate ignored an instruction; ask workers to put key facts in a one-line summary.
- ARCHITECTURE.md ~7755/8500. `entity_keywords.weight` = TF-IDF relevance score (not a count).
- helpContent: `import.meta.glob` auto-discovery; sections carry `bullets`, optional `links:[{to|route, label}]`. Per CONTRACT.md.
- `.claude/` edits crash subagents; root `.md` + `docs/` + `frontend/src` + backend are safe.
