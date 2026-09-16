// Path: src/helpContent/sections/tests.js
// File: tests.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Tests page (/projects/:id/tests) and
//          the test workflow that feeds it (DWB-474).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-09-16 (DWB-571: run-tests button is hidden off the server's own
//          project; DWB-572: force_test_coverage now reads the closing project's repo)

export default {
  key: 'tests',
  title: 'Tests',
  summary: {
    why: 'The test history for one tracked project: run records, performance trends, and failure analysis that feed the sprint test gates.',
    how: 'Post a run from the script or the API, review results and per-test detail, then watch the performance and failures tabs for trends.',
    where: 'The tests link in the project nav (the /projects/:id/tests route).',
  },
  bullets: [
    'Three tabs split the view: results lists each run with drill-down to per-case node id, outcome, and duration; performance charts durations and counts over time; failures breaks down recorded failure records.',
    'The run system tests button appears on one project only: the one whose repo is the repo this dashboard is itself running from. Everywhere else it is hidden, because this server can only execute its own suite, and the endpoint refuses the same way rather than running that suite under another project name.',
    'The canonical workflow is the run_tests.sh script: ./backend/scripts/run_tests.sh --post --project-id N --triggered-by "tester" runs pytest and posts the result back to the project.',
    'Posting a result straight to the API works for any project and is the route to use here. Triggering a run from the page is only available where that button is, so on every other project the script or the API is the only way a record lands.',
    'force_test_run is the gate that reads these runs: it blocks the sprint close unless at least one run exists for this project since the sprint started. Run tests before closing.',
    'force_test_coverage sits alongside it and reads the repo of the project being closed: it maps the routers under backend/app/routers against the test files under backend/tests and blocks the close on any router with no test file. It does not read the runs on this page.',
    'That gate only understands a backend shaped like this one. If the project has no repo path, or has no backend/app/routers and backend/tests to read, the close is refused outright with a message saying so rather than quietly passing or falling back to some other repo. On a different stack, leave it off.',
    'The test gates are not the only close gates: force_standards_audit blocks the close unless a passing standards audit was recorded since the sprint started, and force_coding_standards_md blocks it unless CODING_STANDARDS.md exists at the repo root. See the Audits page for those.',
    'The failures tab maps to the failure taxonomy: seven named manual types (Context Degradation, Spec Drift, Sycophantic Confirmation, Tool Selection Error, Cascading Failure, Silent Failure, Integration Failure) plus the auto-detected rework and test_failure categories.',
  ],
  // DWB-497: cross-links to related sections. DWB-036: audits share close-gate duty.
  links: [
    { to: 'system_tests', label: 'System Tests' },
    { to: 'audits', label: 'Audits' },
    { to: 'tickets', label: 'Tickets' },
  ],
};
