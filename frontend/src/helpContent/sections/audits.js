// Path: src/helpContent/sections/audits.js
// File: audits.js
// Created: 2026-08-12
// Purpose: Help content for the per-project Audits page (/projects/:id/audits,
//          DWB-036). Covers what a standards audit is, PASS/REJECT verdicts, the
//          violations list, the sticks/carrots scorecard, The_Auditor system agent,
//          the alert that fires on every audit, and where the global law lives.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets, links }
// Last Modified: 2026-08-12

export default {
  key: 'audits',
  title: 'Audits',
  summary: {
    why: "A project's standards-audit history: each run checks the staged code against the coding-standards law and records a verdict, the violations, and a per-agent scorecard.",
    how: 'Read the summary stats, then click any audit row to expand who ran it, the violations it found, and the sticks and carrots it handed out.',
    where: 'The audits link in a project nav (the /projects/:id/audits route), between tests and docs.',
  },
  bullets: [
    'A standards audit compares a staged diff against CODING_STANDARDS.md and lands one row per run: a verdict, the violations, and a scorecard, all read live from the project.',
    'The verdict is one of two values: a green PASS badge means the diff conforms, an orange REJECT badge means it does not.',
    'Each violation names the rule, its severity, the file and line it fired on, and a short note, so a REJECT tells you exactly what to fix.',
    'The scorecard is the sticks and carrots ledger: per agent it shows a signed delta (a carrot when positive, a stick when negative) and the reason; those deltas feed the same reputation economy the Team page tracks.',
    'The summary header shows the project and repo plus totals: how many audits ran and the pass and reject counts and percentages.',
    'Rows list newest activity with a ref (the PR when present, otherwise the diff range) and time; clicking one expands it in place to reveal who triggered it, the full violations, and the scorecard.',
    'Every audit is run and attributed to The_Auditor, a fixed global system agent (not a spawned worker); the same audits also surface as a self-refreshing scorecard block on the project overview page.',
    'Recording an audit fires a visible alert every time: an info alert on PASS and a warning alert on REJECT, carrying the audit id, verdict, and any linked ticket.',
    'The global law these audits enforce lives on the Instructions page under Code Standards and deploys to each repo root as CODING_STANDARDS.md.',
    'Two sprint-close gates read this history: force_standards_audit blocks the close unless a PASSING audit was recorded since the sprint started, and force_coding_standards_md blocks it unless CODING_STANDARDS.md exists at the repo root.',
  ],
  // DWB-036: cross-links. Audits feed the reputation economy (team), share sprint
  // close-gate duty with the test gates (tests), and can be tied to a ticket.
  links: [
    { to: 'team', label: 'Team' },
    { to: 'tests', label: 'Tests' },
    { to: 'tickets', label: 'Tickets' },
  ],
};
