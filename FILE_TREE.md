# File Tree

A map of the D'Waantu B'Guantu (DWB) repository: the top-level layout plus the
directories that matter most when finding your way around. Generated from the
working tree; excludes `node_modules`, `.venv`, `.git`, `__pycache__`, `dist`,
and `build`. Counts are approximate and drift as the codebase grows; treat the
annotations, not the numbers, as the durable part.

## Top level

```
d-waantu_b-guantu/
├── backend/            FastAPI + MySQL API: routers, services, models, alembic, tests
├── frontend/           React + Vite dashboard (terminal aesthetic, plain CSS)
├── .claude/            Harness config: playbooks, agent defs, slash commands, settings
├── .dwb/               Agent memory (writable, outside the protected .claude tree)
├── docs/               Source-of-truth playbooks, specs, and rule files
├── scripts/            Repo-level scripts (git hooks installer, post-commit hook)
├── ARCHITECTURE.md     System design and data model
├── README.md           Project overview, setup, full API reference
├── QUICKSTART.md       Fast path to a running dashboard
├── HANDOFF.md          Session-to-session continuity (TL writes at close)
├── INITIAL.md          Original requirements and constraints
├── CHANGELOG.md        Notable changes over time
├── CLAUDE.md           Project rules auto-loaded by every agent
├── FILE_TREE.md        This file
├── docker-compose.yml  MySQL + phpMyAdmin services
├── seed_demo.sql       Demo project seed data
└── seed_personal_dwb.sql   Personal DWB seed data
```

## backend/

FastAPI application following a Router to Service to Model pattern.

```
backend/
├── app/
│   ├── main.py         FastAPI app, CORS, router registration
│   ├── database.py     Engine, SessionLocal, get_db
│   ├── config/         Settings plus tuning tables (session phrases, scoring,
│   │                   memory rules, token budget)
│   ├── models/         SQLAlchemy ORM classes (~27): relationships, enums, constraints
│   ├── schemas/        Pydantic v2 Create/Update/Read models (~26)
│   ├── routers/        HTTP endpoints (~25): one module per domain
│   ├── services/       Business logic (~36): all cross-entity rules live here
│   └── middleware/     Activity logging and error logging middleware
├── alembic/            Migrations
│   └── versions/       Migration revisions (~54)
├── scripts/            Backend CLI scripts (run_tests.sh, sync_instructions.py,
│                       one-off backfills and migrations)
├── tests/              pytest suite (test DB lat_test, transaction rollback per test)
├── alembic.ini         Alembic config
├── pyproject.toml      pytest and tooling config
└── requirements.txt    Python dependencies
```

## frontend/

React 18 + React Router 6 on Vite. State in a single Zustand store. Plain CSS
with custom properties, no Tailwind, no CSS-in-JS.

```
frontend/
├── src/
│   ├── main.jsx        App entry point
│   ├── App.jsx         Route table
│   ├── config.js       Frontend config (API base URL)
│   ├── api/            API client wrappers (~25), one per domain
│   ├── components/     UI components grouped by domain
│   │   ├── agents/
│   │   ├── common/
│   │   ├── dashboard/
│   │   ├── epics/
│   │   ├── help/           Help Center UI
│   │   │   ├── FuzzySearch.jsx        Search box for help sections
│   │   │   ├── CollapsibleSection.jsx Expandable per-domain help block
│   │   │   └── SummaryHeader.jsx      Why/How/Where summary header
│   │   ├── instructions/
│   │   ├── jira/
│   │   ├── layout/         App shell, header, sidebar nav
│   │   ├── project/
│   │   ├── sprints/
│   │   ├── tests/
│   │   └── tickets/
│   ├── helpContent/    Help Center content (data, not UI)
│   │   ├── CONTRACT.md     Authoring contract for help sections
│   │   ├── index.js        Auto-loads sections/*.js via import.meta.glob
│   │   ├── quickStart.js   Quick-start flow and callouts
│   │   └── sections/       One file per domain (dashboard, tickets, team,
│   │                       sessions, tests, docs, system_docs, error_log,
│   │                       archie_channel, comms, jira, system_tests)
│   ├── hooks/          Custom hooks (~14): useAppData master loader,
│   │   │               useFuzzyFilter.js (Help Center search), polling, etc.
│   │   └── useFuzzyFilter.js   Fuzzy filtering for help sections
│   ├── pages/          Route-level pages (~21), thin wrappers over components,
│   │                   includes HelpPage.jsx (the /help route)
│   ├── store/          Zustand store (useStore.js)
│   ├── styles/         All CSS (~19), theme in theme.css, help.css for Help Center
│   └── data/           Static data placeholder
├── public/             Static assets (favicon)
├── index.html          Vite HTML entry
├── package.json        Dependencies and scripts
├── vite.config.js      Vite config
└── vitest.config.js    Vitest config
```

## .claude/

Harness configuration and the deployable doctrine. Subagents must never write
under this path: the permission dialog crashes them. Edits are TL-only.

```
.claude/
├── team_lead_playbook.md       How the TL uses DWB (deployed canon)
├── pm_playbook.md              How the PM uses DWB
├── worker_playbook.md          How all workers use DWB
├── project_rules_team_lead.md  TL's per-repo rules (not overwritten on deploy)
├── project_rules_pm.md         PM's per-repo rules
├── project_rules_worker.md     Worker per-repo rules (stack, ports, conventions)
├── settings.json               Hooks and harness settings
├── settings.local.json         Local settings overrides
├── agents/                     Role agent-def stubs (team-lead, pm, worker,
│   │                           backend/frontend/system-ops/tester) + TEAM template
│   └── active/                 Per-session token-attribution markers
└── commands/                   Slash commands (dwb-open, dwb-close, tl,
                                carrot, stick, score, leaderboard)
```

## .dwb/

Agent memory, moved here (DWB-401) so it sits outside the protected `.claude/`
tree and stays writable. Write through the memory API for the timestamp heading
and passive trim.

```
.dwb/
└── memory/
    └── DWB/                 One directory per agent on the DWB project
        └── <AgentName>/
            ├── identity.md      System-generated profile (never hand-edit)
            └── memory.md        Free-form durable memory (append-only via API)
```

## docs/

The authored source of truth for playbooks and rules. Playbooks here are the
canonical copies; the `.claude/*_playbook.md` files are deployed from these.

```
docs/
├── team_lead_playbook.md   Canonical TL playbook
├── pm_playbook.md          Canonical PM playbook
├── worker_playbook.md      Canonical worker playbook
├── session_lifecycle.md    DWB session model (open/close, single-active, rollup)
├── agent_scoring_spec.md   Reputation and scoring spec
├── PASSIVE_TRACKING_PLAN.md  Token/time tracking design
├── ROADMAP_PHASE2.md       Forward-looking roadmap
├── handoff/                Deep-dive handoff notes (playbook enforcement)
└── rules/
    └── global/             Individual rule files synced to the DB
                            (code headers, commit style, naming, stop-means-stop,
                            test-run-per-sprint, no CSS frameworks, etc.)
```

## scripts/

```
scripts/
├── install-git-hooks.sh    Installs the repo git hooks
└── hooks/
    └── post-commit         Post-commit hook
```
