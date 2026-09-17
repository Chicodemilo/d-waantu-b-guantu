// Path: src/helpContent/sections/docs.js
// File: docs.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Docs view (DWB-471). Default-exports one
//          help section object describing /projects/:id/docs backed by GET /api/projects/:id/docs.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-09-17 (DWB-574: the no-separate-docs project is identified by a repo
//          path comparison, not by name, so the sentence survives a clone)

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
    'One project has no separate docs: the one whose repo is the repo this dashboard runs from, since its docs are the system docs. That project points you to system_docs in the Overview nav instead, and it is decided by comparing repo paths, not by the project name.',
    'A project needs a configured repo path for this view to load.',
    'CODING_STANDARDS.md is a companion repo-root doc: when force_coding_standards_md is enabled, its absence at the repo root blocks the sprint close, and its rules are what the standards audits enforce.',
  ],
  // DWB-497: cross-links to related sections. DWB-036: CODING_STANDARDS.md ties to audits.
  links: [
    { to: 'system_docs', label: 'System Docs' },
    { to: 'audits', label: 'Audits' },
  ],
};
