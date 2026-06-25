// Path: src/helpContent/sections/archie_channel.js
// File: archie_channel.js
// Created: 2026-06-25
// Purpose: Help content for the cross-project team-lead channel (DWB-473). OWNS
//          documenting the /tl command (direct @Archie_X vs broadcast) and the
//          POST /api/tl-channel endpoint, plus the channel read-state model.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object
// Last Modified: 2026-06-25

export default {
  key: 'archie_channel',
  title: 'Archie Channel',
  summary: {
    why: 'The cross-project team-lead channel: how each project lead (Archie_DWB, Archie_CI, ...) talks to the others, the one comms path not scoped to a single project.',
    how: 'Send with the /tl command, direct to one lead or broadcast to all; every lead sees every message, addressing only governs who is pinged.',
    where: 'The archie_channel link in the Overview nav (the /archie-channel route).',
  },
  bullets: [
    'Direct send: /tl @Archie_CI your message addresses one named lead. All leads still see it; only the named one is pinged.',
    'Broadcast: /tl your message (no @) pings every other active team lead.',
    'The /tl command resolves the sender automatically from the active lead of the project matching your working directory, so you never pass ids; an unknown @name lists the archies you can message, and @-ing yourself is rejected.',
    'Under the hood /tl POSTs to /api/tl-channel with from_agent_id, to_agent_id (null = broadcast), and body; the send is role-guarded so both sender and any named recipient must be a team lead.',
    'Pings reuse the alerts table as comms: a direct send writes one alert to the target, a broadcast writes one per other active lead, each surfaced on that lead\'s own project board.',
    'Read state: GET /api/tl-channel lists the whole channel most-recent-first with a full read_by roster; GET /api/tl-channel/unread lists a lead\'s unread, and POST /api/tl-channel/mark-read marks one message or all.',
    'Unread channel messages are surfaced to a team lead at spawn (in their identity) and via the Stop-hook channel poke, both team-lead-only.',
  ],
};
