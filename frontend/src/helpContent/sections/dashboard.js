// Path: src/helpContent/sections/dashboard.js
// File: dashboard.js
// Created: 2026-06-25
// Purpose: Help content for the Dashboard (home) view (DWB-472). Also the copy-this
//          template referenced by CONTRACT.md, including the optional DWB-496
//          cross-link (`links`) field. Default-exports one help section object
//          describing what the dashboard shows and how to use it.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets, links }
// Last Modified: 2026-06-25

export default {
  key: 'dashboard',
  title: 'Dashboard',
  summary: {
    why: 'The home view: a cross-project glance at health, alerts, projects, tokens, and agents.',
    how: 'Scan the summary and open alerts, then click a project card to drill in or add a new one.',
    where: 'The dashboard link at the top of the Overview nav (home route).',
  },
  bullets: [
    'Summary up top gives the cross-project rollup at a glance.',
    'Open Alerts shows only surfaced categories (comms, scoring, actionable); use clear all to dismiss them.',
    'Each alert row links to its project; severity is color-coded (critical, warning, info).',
    'Add a project from a repo path with "add project", or load sample data with "seed demo project".',
    'Project cards link into each project; Time & Tokens and Token Audit summarize spend.',
    'The Agents section is a sortable table; click a row to open that agent.',
  ],
  // DWB-496/497: section cross-links; DWB-501: portal link to the live page.
  links: [
    { route: '/', label: 'Open the dashboard' },
    { to: 'tickets', label: 'Tickets' },
    { to: 'team', label: 'Team' },
    { to: 'sessions', label: 'Sessions' },
  ],
};
