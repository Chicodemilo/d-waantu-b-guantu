// Path: src/helpContent/sections/jira.js
// File: jira.js
// Created: 2026-06-25
// Purpose: Help content for the optional per-project Jira integration view (DWB-475).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-06-25

export default {
  key: 'jira',
  title: 'Jira',
  summary: {
    why: 'An optional one-to-one link between DWB tickets and Jira issues; DWB reads Jira, it never writes it.',
    how: 'Enable Jira in the project Tools panel, then link a ticket to its Jira issue from the ticket detail page.',
    where: 'The jira link under a project, shown only once Jira is enabled.',
  },
  bullets: [
    'Enable from the project Tools panel; the Jira project key and base url are set together, so a half-enabled state is rejected.',
    'Link a ticket from its detail page by entering a Jira issue key; the mapping is one-to-one and a key already linked elsewhere returns 409.',
    'Disabling clears the Jira key from every ticket on the project and from the project itself, and reports how many tickets were cleared; the Jira issues themselves are never touched.',
    'The Jira page is a read-only snapshot with fuzzy search and sortable columns; the sync button pulls the latest Jira state on demand.',
    'A ticket can be unlinked on its own without disabling Jira for the whole project.',
  ],
  // DWB-497: cross-links to related sections.
  links: [
    { to: 'tickets', label: 'Tickets' },
  ],
};
