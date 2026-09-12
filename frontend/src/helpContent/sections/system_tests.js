// Path: src/helpContent/sections/system_tests.js
// File: system_tests.js
// Created: 2026-06-25
// Purpose: Help content for the system Tests view (/tests) - the DWB platform's
//          own test suite, distinct from per-project tests (DWB-474).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-08-12 (DWB-036: note standards-audit close gates + audits cross-link)

export default {
  key: 'system_tests',
  title: 'System Tests',
  summary: {
    why: "Tracks the health of the DWB platform's own test suite, not the tests of any project DWB tracks.",
    how: 'Run the suite on demand, then drill into any run to see which cases passed or failed and how router coverage looks.',
    where: 'The system_tests link in the Overview nav (the /tests route).',
  },
  bullets: [
    'The run system tests button executes the backend pytest suite and records a new run; results stream back with passed, failed, and total counts plus a tail of the live output.',
    'Runs list newest-first; click one to open its detail and see every test case with its node id, pass or fail mark, and duration in milliseconds.',
    'Use the passed and failed toggles on a run to filter the case list down to just those outcomes.',
    'The coverage table lists each backend router, the test file that covers it (or missing), and an overall covered count; this is what the force_test_coverage gate checks.',
    'force_test_coverage is one of a wider set of sprint-close gates on a tracked project: alongside it, force_standards_audit requires a passing standards audit in the sprint window and force_coding_standards_md requires CODING_STANDARDS.md at the repo root.',
    'These runs cover DWB itself, so they are recorded against the DWB project rather than a tracked project.',
  ],
  // DWB-497: section cross-links; DWB-501: portal link; DWB-036: audits close gate.
  links: [
    { route: '/tests', label: 'Open system tests' },
    { to: 'tests', label: 'Project Tests' },
    { to: 'audits', label: 'Audits' },
    { to: 'system_docs', label: 'System Docs' },
  ],
};
