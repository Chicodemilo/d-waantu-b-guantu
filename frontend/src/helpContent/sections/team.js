// Path: src/helpContent/sections/team.js
// File: team.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Team view, roster and reputation scoring (DWB-475).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets }
// Last Modified: 2026-06-25

export default {
  key: 'team',
  title: 'Team',
  summary: {
    why: 'The project roster plus a peer-driven reputation economy that tracks who is pulling weight.',
    how: 'Read the leaderboard, then award or dock reputation with the scoring commands or the inline buttons.',
    where: 'The team link under any project in the sidebar.',
  },
  bullets: [
    'The Roster tab lists each agent with name, score, type, role, and active status; the Scoreboard tab ranks agents by reputation with rank, tier, sprint delta, and remaining influence.',
    'Reputation moves automatically from work (closing tickets, overhead) and from human awards and peer scoring; the ledger on an agent page shows the last entries with delta, reason, and actor.',
    'Peer scoring spends from a per-sprint influence budget and is guarded: no self-scoring, a per-sprint budget cap, and per-target demerit caps; human awards cost no influence.',
    '/carrot <agent> <points> "reason" awards positive reputation and broadcasts to the team.',
    '/stick <agent> <points> "reason" docks reputation and broadcasts to the team.',
    '/score <agent> prints one agent reputation, sprint delta, influence, and recent ledger.',
    '/leaderboard prints the whole-project table of reputation, sprint delta, and influence.',
  ],
  // DWB-497: cross-links to related sections.
  links: [
    { to: 'tickets', label: 'Tickets' },
    { to: 'sessions', label: 'Sessions' },
  ],
};
