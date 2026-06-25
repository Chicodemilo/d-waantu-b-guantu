// Path: src/helpContent/sections/sessions.js
// File: sessions.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Sessions views (DWB-473). Covers the
//          DWB session lifecycle: open/close detection, the single-active rule,
//          and the token/time rollup. Cross-references /dwb-open and /dwb-close
//          (owned by the quick-start section), does not document them here.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object
// Last Modified: 2026-06-25

export default {
  key: 'sessions',
  title: 'Sessions',
  summary: {
    why: 'A DWB session is the intent boundary around a span of work, rolling up all the time and tokens spent on a project.',
    how: 'Open by signaling you want to start, close when you stop, then read the rollup; the system attributes everything in between for you.',
    where: 'The Sessions link in a project nav (list, current, and detail views).',
  },
  bullets: [
    'A DWB session is not a Claude Code session: one DWB session rolls up the TL window, every spawned worker, and every subagent under a single span.',
    'Opens are detected in two layers: a regex fast path on common phrases (fires synchronously on your prompt) and TL reasoning for the long tail (acts when confident, asks one question when ambiguous).',
    'The /dwb-open and /dwb-close slash commands are the deterministic escape hatch; they are documented in the quick-start section.',
    'At most one session is open per project at a time (DB-enforced): a second open returns 409 with the already-active session, and racing opens resolve to exactly one winner.',
    'Closing mirrors opening; a confident AI close must carry a 5 to 10 word headline (it becomes the dashboard summary) or it is rejected.',
    'Forget to close and a background idle sweeper auto-closes the session after a long idle window (10 hours by default, configurable via IDLE_TIMEOUT_MINUTES), tagged as an idle timeout so it reads differently from an explicit close.',
    'On close, total_tokens (summed across every linked hook session) and total_time_seconds (wall clock, open to close) roll onto the session row.',
    'The detail view breaks tokens down by role, by ticket, and into the TL, PM, and Ad Hoc overhead buckets.',
    'Sessions are scoped per project, so Archie_DWB and Archie_CI can each hold an open session in parallel with no cross-contamination.',
  ],
};
