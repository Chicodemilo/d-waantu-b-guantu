// Path: src/helpContent/quickStart.js
// File: quickStart.js
// Created: 2026-06-25
// Purpose: Quick-start content for the top of the Help Center (DWB-470). `flow` is
//          the linear ordered startup sequence from install through closing the
//          session; `callouts` are standalone shortcuts rendered as separate blocks
//          (NOT chained to the flow). Shape is documented in CONTRACT.md.
// Caller: helpContent/index.js -> pages/HelpPage.jsx
// Callees: none (plain data)
// Data In: none
// Data Out: default export { flow: [{title, detail}], callouts: [{title, detail}] }
// Last Modified: 2026-06-25

export default {
  flow: [
    {
      title: 'Install',
      detail: 'Clone the repo and copy .env.example to .env. Then install dependencies: a Python venv with pip install -r requirements.txt in backend/, and npm install in frontend/.',
    },
    {
      title: 'Bring it up',
      detail: 'Start MySQL with docker compose up -d, apply migrations with alembic upgrade head, run the API with uvicorn app.main:app --port 8000 --reload, and start the frontend with npm run dev. The dashboard is at http://localhost:5173.',
    },
    {
      title: 'Tell Archie to read the playbook',
      detail: 'In your project Claude Code session, type "you are archie, read your playbook". Archie, your team lead, reads the playbook, pulls the live roster, open alerts, the active sprint, and HANDOFF.md, then reports current state. A DWB session opens automatically (a hook catches the phrase), so time and tokens are tracked from here on and you manage none of it. This is the single entry point. (Manual escape hatch: run /dwb-open.)',
    },
    {
      title: 'Create a project',
      detail: 'Point the team at your repo with POST /api/projects/from-repo; it auto-detects the name, prefix, and description. Everything in DWB hangs off a project.',
    },
    {
      title: 'Build the team',
      detail: 'Create agents with POST /api/agents and link them to the project with POST /api/project-agents. Archie always leads; add a PM only at three or more workers, plus workers as the project needs.',
    },
    {
      title: 'Open an epic and a sprint',
      detail: 'Create an epic with POST /api/epics, then a sprint with POST /api/sprints that auto-attaches to it. The hierarchy is Project -> Epic -> Sprint -> Ticket, so a ticket needs both parents. Name the sprint from its goal.',
    },
    {
      title: 'File and work tickets',
      detail: 'The PM files tickets with POST /api/tickets, which auto-assign to the active sprint and inherit the epic. Workers move them todo -> in_progress -> in_review; Archie reviews and closes.',
    },
    {
      title: 'Close the session and write the handoff',
      detail: 'When you are done, type a close phrase: "shut it down for the night", "wrap up archie", "done for the night", or run /dwb-close. Archie lets workers land their wrap-ups, trims any over-ceiling docs, closes the DWB session (recording a short headline summary for the sessions page), and writes HANDOFF.md last so the next session inherits accurate state. Closing is the bookend to the open: it finalizes the full token and time rollup.',
    },
  ],
  callouts: [
    {
      title: 'Make a quick project',
      detail: 'Skip the manual setup. POST /api/projects/from-repo with {"repo_path": "/path/to/repo"} auto-detects the project name, prefix, and description straight from the repo, so you start tracking in one step.',
    },
    {
      title: 'Seed a demo',
      detail: 'Explore the dashboard with realistic data and no repo wiring. POST /api/projects/seed-demo creates a fully populated demo project so you can see every view in action.',
    },
  ],
};
