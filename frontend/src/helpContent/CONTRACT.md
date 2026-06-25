<!--
Path: src/helpContent/CONTRACT.md
File: CONTRACT.md
Created: 2026-06-25
Purpose: Content contract for the Help Center (DWB-469). Read this before authoring
         any help section. Defines the per-domain file shape, the canonical section
         keys, the quick-start shape, and where files go. The HelpPage renders
         whatever section files exist, so content lands incrementally.
Caller: human + content-author agents (Sylvie, Dolores, Barry_DWB, Sage, Pam_DWB, Freddie)
Last Modified: 2026-06-25
-->

# Help Center content contract (DWB-469)

You author **one file per domain**. Drop it in `src/helpContent/sections/` and it
appears on `/help` automatically. No index edits, no imports to wire up: the index
auto-discovers every `sections/*.js` via `import.meta.glob`.

## Where files go

```
src/helpContent/
  index.js              <- auto-loads sections/*.js, orders by NAV_GROUPS (DO NOT touch)
  quickStart.js         <- the top quick-start region (DWB-470 owns the content)
  sections/
    dashboard.js        <- example / template (already exists)
    tickets.js          <- you add files like this
    team.js
    ...
```

## Per-domain section shape

Each `sections/<key>.js` **default-exports a single object** in this exact shape:

```js
// Path: src/helpContent/sections/tickets.js
// File: tickets.js
// Created: 2026-06-25
// Purpose: Help content for the per-project Tickets page (DWB-4xx).
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object
// Last Modified: 2026-06-25

export default {
  key: 'tickets',              // REQUIRED, must match a canonical key below
  title: 'Tickets',            // REQUIRED, display heading
  summary: {                   // REQUIRED object; any field may be '' if N/A
    why: 'One short sentence: what this view is for.',
    how: 'One short sentence, weighted toward HOW you use it.',
    where: 'Very short: how to reach it (nav path).',
  },
  bullets: [                   // REQUIRED array (may be empty); weight toward HOW
    'Concrete thing you can do here.',
    'Another action or behavior worth knowing.',
  ],
  links: [                     // OPTIONAL (DWB-496); cross-links to related sections
    { to: 'jira', label: 'Jira integration' },
  ],
};
```

Rules:
- `key` MUST be one of the canonical keys below. An unknown key will not render.
- Keep `summary.why/how/where` to single short sentences. `where` is the shortest.
- `bullets` carry the detail and should be weighted to **How** (actions, behaviors),
  not background. Plain strings. No icons, no em-dashes.
- Be accurate to the real UI: open the page you are documenting and describe what
  is actually there.

## Cross-links between sections (DWB-496)

A section may declare an optional `links` array to point readers at related
sections. This is a **structured** field, not an inline string token, and it is
fully backward-compatible: `bullets` stay plain strings, and `links` is optional.

```js
links: [
  { to: 'tickets', label: 'Tickets' },   // `to` MUST be a canonical section key
  { to: 'jira', label: 'Jira integration' },
]
```

- `to` (REQUIRED): the canonical `key` of the target section.
- `label` (REQUIRED): the clickable text shown to the reader.
- Rendered as a "See also" row at the bottom of the section body. Clicking a link
  force-opens the target section (reusing the same force-open plumbing as fuzzy
  search) AND scrolls it into view. Any active search filter is cleared first so
  the target is reachable.
- A link whose `to` does not resolve to an existing section is silently skipped,
  so it is safe to author a link before its target file lands.
- Keep cross-links relevant and few per section. Plain text labels, no icons.

## Canonical section keys (render order mirrors the sidebar nav)

Overview group:
- `dashboard`        (sidebar: dashboard)
- `system_tests`     (sidebar: system_tests)
- `system_docs`      (sidebar: system_docs)
- `error_log`        (sidebar: error_log)
- `archie_channel`   (sidebar: archie_channel)

Per-project group:
- `tickets`          (sidebar: tickets)
- `team`             (sidebar: team)
- `sessions`         (sidebar: sessions)
- `tests`            (sidebar: tests)
- `docs`             (sidebar: docs)
- `comms`            (sidebar: inter-agent comms)
- `jira`             (sidebar: jira)

## Quick-start shape (quickStart.js, DWB-470)

```js
export default {
  flow: [                      // ordered, linear startup steps (render as a numbered list)
    { title: 'Start the dashboard', detail: 'One sentence on the step.' },
    { title: 'Create a project', detail: '...' },
  ],
  callouts: [                  // standalone shortcuts, rendered as SEPARATE blocks
    { title: 'Make a quick project', detail: '...' },
    { title: 'Seed a demo', detail: '...' },
  ],
};
```

The flow and the callouts render as two visually distinct regions. They are NOT
chained together.
