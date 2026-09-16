// Path: src/helpContent/sections/audits.js
// File: audits.js
// Created: 2026-08-12
// Purpose: Help content for the per-project Audits page (/projects/:id/audits,
//          DWB-036). Covers what a standards audit is, PASS/REJECT verdicts, the
//          violations list, the sticks/carrots scorecard, The_Auditor system agent,
//          the alert an audit raises, and where the global law lives.
// Caller: helpContent/index.js (auto-discovered via import.meta.glob)
// Callees: none (plain data)
// Data In: none
// Data Out: default export: one help section object { key, title, summary, bullets, links }
// Last Modified: 2026-09-16 (DWB-570: corrected the law's location, the scorecard's
//          effect on reputation, the alert absolute, and the attribution a reader sees)

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
    'The scorecard is the proposed sticks and carrots: per agent it shows a signed delta (a carrot when positive, a stick when negative) and the reason. Recording an audit does not move any reputation on its own; the deltas only land on the Team page once someone applies the scorecard.',
    'The summary header shows the project and repo plus totals: how many audits ran and the pass and reject counts and percentages.',
    'Rows list newest activity with a ref (the PR when present, otherwise the diff range) and time; clicking one expands it in place to reveal who triggered it, the full violations, and the scorecard.',
    'Audits are attributed to The_Auditor, a fixed global system agent rather than a spawned worker, which is the name they carry in the activity feed and on their alerts. The expanded row shows the raw triggered_by the runner sent instead, usually auditor_script.',
    'The same audits surface as a self-refreshing scorecard block on the project overview page, which repolls on its own every half minute.',
    'Recording an audit raises a visible alert: an info alert on PASS and a warning alert on REJECT, carrying the audit id, verdict, and any linked ticket. It is skipped in the rare case where no agent can be named as the raiser.',
    'The global law these audits enforce is the coding-standards sheet kept in the DWB repo at docs/rules/global/coding-standards.md, which deploys to each tracked repo root as CODING_STANDARDS.md.',
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
