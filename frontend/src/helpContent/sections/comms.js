// Path: src/helpContent/sections/comms.js
// File: comms.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Inter-Agent Comms view (DWB-472).
//          Default-exports one help section object describing the captured
//          agent-to-agent message log and how to read/manage it.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-06-25

export default {
  key: 'comms',
  title: 'Inter-Agent Comms',
  summary: {
    why: 'A live log of the messages agents send each other on this project.',
    how: 'Skim newest-first to follow who told whom what; hover a row for the full message.',
    where: 'The inter-agent comms link in a project\'s nav.',
  },
  bullets: [
    'Each row shows from -> to, a timestamp, and the message (truncated to one line).',
    'Hover any row to read the full untruncated message.',
    'The list polls every few seconds, so new traffic appears without a refresh.',
    'Use clear to wipe this project\'s log; it asks for an inline confirm first.',
    'Capture is toggled per project by capture_agent_comms in the project Tools panel; old messages auto-purge after a few days.',
  ],
  // DWB-497: cross-links to related sections.
  links: [
    { to: 'archie_channel', label: 'Archie Channel' },
    { to: 'team', label: 'Team' },
  ],
};
