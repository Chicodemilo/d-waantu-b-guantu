// Path: src/helpContent/sections/tickets.js
// File: tickets.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Tickets view (DWB-475).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-06-25

export default {
  key: 'tickets',
  title: 'Tickets',
  summary: {
    why: 'Tickets are the atomic units of work, nested project then epic then sprint then ticket.',
    how: 'Create a ticket and it auto-assigns to the active sprint; move its status as the work progresses.',
    where: 'The tickets link under any project in the sidebar.',
  },
  bullets: [
    'Status flows through backlog, todo, in_progress, in_review, done, and cancelled; a worker moves it to in_progress on start and to in_review when ready for review.',
    'Create a ticket with project_id, a title, a ticket_number unique per project, and a globally unique ticket_key like DWB-475; a collision returns 409.',
    'Leave the sprint off and the ticket auto-assigns to the project active sprint and inherits that sprint epic; with no active sprint the create returns 400.',
    'Ticket types are task, bug, story, and subtask; a subtask needs a parent_ticket_id and inherits the parent sprint and epic, and renders indented under its parent in the list.',
    'The ticket_key (DWB-475) is the human label; the database id is what API paths use, and the two are not interchangeable.',
    'The detail page shows description, stats, status history, comments, and the Jira link widget when Jira is enabled.',
  ],
};
