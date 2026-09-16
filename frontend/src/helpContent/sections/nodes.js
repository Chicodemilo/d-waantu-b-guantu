// Path: src/helpContent/sections/nodes.js
// File: nodes.js
// Created: 2026-09-16
// Purpose: Help content for the per-project Nodes page (/projects/:id/nodes,
//          DWB-570). Covers the weighted cloud and its headliner tier, the
//          substring limiter and the connections toggle, the pointer-kind
//          filter, the detail overlay and neighbour hops, the rescan control,
//          and the scan exclusions with the directory browser.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets, links }
// Last Modified: 2026-09-16

export default {
  key: 'nodes',
  title: 'Nodes',
  summary: {
    why: "A project's repo indexed as a cloud of weighted tags, each one pointing back at every place it appears in the code, docs, and agent memory.",
    how: 'Skim the cloud for the heavy tags, type to limit it, then click one to read its pointers and hop through its neighbours.',
    where: 'The nodes link in a project nav (the /projects/:id/nodes route), between docs and inter-agent comms.',
  },
  bullets: [
    'Each node is sized by weight across nine tiers; the heaviest half a percent (at least one) render as headliners above the eight regular sizes. The scale is pinned to the full set, so limiting the cloud never resizes what stays.',
    'The search box is a limiter, not a jump: a case-insensitive substring match on the node name over the already-loaded set. Non-matches disappear, and Esc or the clear link restores the whole cloud.',
    'Turn on "+ connections" while limiting to add the first-degree neighbours of the matches in a dimmed style. It only enables when the search is down to 25 matches or fewer; above that it tells you to narrow further.',
    'The kind row toggles pointer kinds, showing only the kinds the scan actually produced for this project (code, doc, and memory today). Kind and search compose, so a node must pass both; turning every kind off gives you a select all link back.',
    'Click any node to open its detail: tag, weight, its pointers grouped by kind with the file ref and line range, and the neighbours derived from the refs they share.',
    'Clicking a neighbour hops to it in place rather than opening a second panel, and a breadcrumb trail lets you step back the way you came.',
    'The head counts the nodes and pointers in the index and says when it was last built, or "never indexed" if it never has been.',
    'rescan rebuilds the entire index behind an inline "rescan? yes / cancel" confirm. The pass runs for a couple of minutes with no progress to watch, then reports how many tags were grounded, how many were suppressed, and how many pointers it wrote.',
    'exclusions opens the list of repo-relative patterns the scan skips. Add one by typing a pattern or by picking a directory in the browser, and delete any of them through the same inline confirm; the seeded defaults are ordinary rows you can remove like the rest.',
  ],
  // DWB-570: cross-links. Pointers land on docs, tickets, and agent memory, so
  // those are the sections a reader follows next.
  links: [
    { to: 'docs', label: 'Docs' },
    { to: 'tickets', label: 'Tickets' },
    { to: 'sessions', label: 'Sessions' },
  ],
};
