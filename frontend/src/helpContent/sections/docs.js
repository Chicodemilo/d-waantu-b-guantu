// Path: src/helpContent/sections/docs.js
// File: docs.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Docs view (DWB-471). Default-exports one
//          help section object describing /projects/:id/docs backed by GET /api/projects/:id/docs.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-08-12 (DWB-036: note CODING_STANDARDS.md close gate + audits cross-link)

export default {
  key: 'docs',
  title: 'Docs',
  summary: {
    why: "A project's living docs, read straight from its repo so they never drift from the code.",
    how: 'Click a doc to expand its raw contents inline; missing files show where to create them.',
    where: "docs in a project's sub-nav.",
  },
  bullets: [
    'Shows README, QUICKSTART, ARCHITECTURE, and HANDOFF read live from the project repo, so the page mirrors what is on disk.',
    'Click a doc name or its caret to expand the full file inline; click again to collapse.',
    'Each card shows the absolute file path; edit there and refresh and the page re-reads it, with nothing to publish.',
    'Files that do not exist are grouped below a divider with a missing badge and the expected path where you can create them.',
    'The DWB project has no separate docs: this view points you to system_docs in the Overview nav instead.',
    'A project needs a configured repo path for this view to load.',
    'CODING_STANDARDS.md is a companion repo-root doc: when force_coding_standards_md is enabled, its absence at the repo root blocks the sprint close, and its rules are what the standards audits enforce.',
  ],
  // DWB-497: cross-links to related sections. DWB-036: CODING_STANDARDS.md ties to audits.
  links: [
    { to: 'system_docs', label: 'System Docs' },
    { to: 'audits', label: 'Audits' },
  ],
};
