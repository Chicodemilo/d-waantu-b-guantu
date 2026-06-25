// Path: src/helpContent/sections/error_log.js
// File: error_log.js
// Created: 2026-06-25
// Purpose: Help content for the system-wide Error Log view (DWB-473). Covers the
//          /errors page (source/project filters, stack-trace expansion) plus the
//          client error logging endpoints (errors + client-logs telemetry feed).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object
// Last Modified: 2026-06-25

export default {
  key: 'error_log',
  title: 'Error Log',
  summary: {
    why: 'One place to see failures across the whole system: backend exceptions, frontend crashes, and hook failures from every project.',
    how: 'Scan the most-recent-first list, filter by source or project, and click a row to expand its stack trace.',
    where: 'The error_log link in the Overview nav (the /errors route).',
  },
  bullets: [
    'The list auto-refreshes every 10 seconds; hit "$ refresh" to pull immediately.',
    'Each row is tagged with its source: [BE] backend, [FE] frontend, or [HK] hook, plus the project prefix, HTTP status code (500s highlighted), endpoint, and message.',
    'Filter by source and by active project; the two filters compose. Click any row to expand the error type, origin (file:function:line), and full stack trace.',
    'Errors are written via POST /api/errors with a source of backend, frontend, or hook; query them with GET /api/errors using project_id, source, and limit (default 50, capped at 200).',
    'A separate frontend telemetry feed batches lower-severity logs to POST /api/client-logs under a lenient never-5xx contract: malformed records drop individually and the rest still land.',
    'Each client log carries a level (debug, info, warn, error), a category, and an optional route; query them with GET /api/client-logs by level, category, route, or since.',
    'Hook scripts always exit 0, so a logged hook error never blocks the caller.',
  ],
};
