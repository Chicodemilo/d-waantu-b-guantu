// Path: src/helpContent/sections/tests.js
// File: tests.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Tests page (/projects/:id/tests) and
//          the test workflow that feeds it (DWB-474).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-06-25

export default {
  key: 'tests',
  title: 'Tests',
  summary: {
    why: 'The test history for one tracked project: run records, performance trends, and failure analysis that feed the sprint test gates.',
    how: 'Run the suite, review results and per-test detail, then watch the performance and failures tabs for trends.',
    where: 'The tests link in the project nav (the /projects/:id/tests route).',
  },
  bullets: [
    'Three tabs split the view: results lists each run with drill-down to per-case node id, outcome, and duration; performance charts durations and counts over time; failures breaks down recorded failure records.',
    'The run system tests button triggers the suite and refreshes the run list with the new pass, fail, and total counts.',
    'The canonical workflow is the run_tests.sh script: ./backend/scripts/run_tests.sh --post --project-id N --triggered-by "tester" runs pytest and posts the result back to the project.',
    'You can also post a result straight to the API, or trigger a run from the page; every path lands a record on this page.',
    'Two gates read these runs at sprint close: force_test_run blocks the close unless at least one run exists since the sprint started, and force_test_coverage blocks it if any router lacks a test file. Run tests before closing.',
    'The failures tab maps to the failure taxonomy: seven named manual types (Context Degradation, Spec Drift, Sycophantic Confirmation, Tool Selection Error, Cascading Failure, Silent Failure, Integration Failure) plus the auto-detected rework and test_failure categories.',
  ],
  // DWB-497: cross-links to related sections.
  links: [
    { to: 'system_tests', label: 'System Tests' },
    { to: 'tickets', label: 'Tickets' },
  ],
};
