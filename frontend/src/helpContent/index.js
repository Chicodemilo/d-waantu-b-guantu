// Path: src/helpContent/index.js
// File: index.js
// Created: 2026-06-25
// Purpose: Help Center content index (DWB-469). Auto-discovers every
//          sections/*.js module via import.meta.glob, keys them by their
//          section.key, and orders them into NAV_GROUPS that mirror the
//          sidebar nav. The page renders whatever sections exist, so content
//          authored against CONTRACT.md lands incrementally with no edits here.
// Caller: pages/HelpPage.jsx
// Callees: ./quickStart, ./sections/*.js (glob), Vite import.meta.glob
// Data In: section modules (default-exported objects per CONTRACT.md)
// Data Out: helpGroups (ordered groups of existing sections), allSections,
//           NAV_GROUPS (the canonical ordering), quickStart
// Last Modified: 2026-06-25

import quickStart from './quickStart';

// Canonical ordering, mirroring the sidebar nav (Sidebar.jsx).
export const NAV_GROUPS = [
  {
    id: 'overview',
    label: 'Overview',
    keys: ['dashboard', 'system_tests', 'system_docs', 'error_log', 'archie_channel'],
  },
  {
    id: 'project',
    label: 'Per-project',
    keys: ['tickets', 'team', 'sessions', 'tests', 'docs', 'comms', 'jira'],
  },
];

// Auto-discover authored section files. Eager so the data is available synchronously.
const modules = import.meta.glob('./sections/*.js', { eager: true });

const byKey = {};
for (const path in modules) {
  const section = modules[path] && modules[path].default;
  if (section && section.key) {
    byKey[section.key] = section;
  }
}

// Resolve each group's existing sections in canonical order. Missing files are
// simply skipped, so the page fills in as authors add content.
export const helpGroups = NAV_GROUPS.map((group) => ({
  id: group.id,
  label: group.label,
  sections: group.keys.map((k) => byKey[k]).filter(Boolean),
})).filter((group) => group.sections.length > 0);

export const allSections = helpGroups.flatMap((group) => group.sections);

export { quickStart };
