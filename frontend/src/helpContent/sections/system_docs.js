// Path: src/helpContent/sections/system_docs.js
// File: system_docs.js
// Created: 2026-06-25
// Purpose: Help content for the System Docs view (DWB-471). Default-exports one
//          help section object describing the /docs page backed by GET /api/system/docs.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-06-25

export default {
  key: 'system_docs',
  title: 'System Docs',
  summary: {
    why: 'Read the DWB system docs live from the repo root without leaving the dashboard.',
    how: 'Click a doc to expand its raw contents inline; missing files show where to create them.',
    where: 'system_docs in the Overview nav.',
  },
  bullets: [
    'Shows README, QUICKSTART, and ARCHITECTURE read straight from the DWB repo root, so the page always reflects what is on disk.',
    'Click a doc name or its caret to expand the full file inline; click again to collapse.',
    'Each card shows the absolute file path, so you know exactly which file to edit.',
    'Edit a doc at the shown path and refresh; the page re-reads the file, there is nothing to publish.',
    'Files that do not exist are grouped below a divider with a missing badge and the expected path.',
  ],
};
