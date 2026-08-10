# Coding Standards

> Language conventions, naming, error handling, testing, documentation, and code review expectations for the DWB codebase. The atomic rules in `docs/rules/global/` are the enforceable source of truth; when this doc and a rule file disagree, the rule file wins.

## Languages & Style

- Backend: Python 3 / FastAPI / SQLAlchemy 2.0 / Alembic. Frontend: JavaScript (not TypeScript) / React 18 / Vite.
- There is deliberately no ruff/black/eslint/prettier config. Consistency comes from matching the surrounding code and from review. Do not add formatter configs or reformat files wholesale.
- Plain CSS only: no Tailwind, no CSS-in-JS. Preserve the terminal aesthetic.

## Naming

- Python: snake_case functions/variables, PascalCase classes. Type hints on all signatures, modern syntax (`int | None`, not `Optional[int]`).
- Frontend: PascalCase component files, one component per file. kebab-case CSS classes in per-feature stylesheets (`tickets.css`, `dashboard.css`) or `common.css` when genuinely shared.
- Alembic revisions: `<revision>_<snake_case_description>.py`, hand-written (MySQL autogenerate is not trusted).

## Services & Logic

- Logic is farmed out to reusable services, front end and back end — not embedded in views, routes, or components.
- Backend: business logic lives in `backend/app/services/` (one module per domain); routers stay thin. Cross-entity rules always go in a service.
- Frontend: shared client logic lives in `frontend/src/services/` (`logger.js`, caches, tracking); API access in `src/api/`; view-shaped logic in hooks.
- New service files get a clear name and a header explaining usage (what calls it, what it calls).
- When planning new system functionality, look in the `services/` directories first for something that already does the job.

## Scripts

- Worker scripts live in a `scripts/` directory: repo-level scripts (git hooks installer) in `/scripts`, backend CLI scripts (`run_tests.sh`, `sync_instructions.py`, backfills) in `backend/scripts/`.
- Anything that may run on a server or locally belongs there — shell, Python, seeders, deploy scripts — each with documentation: what it does, how to run it, and from where.
- Scripts read configuration from `.env` even when run locally. They get committed, so no hard-coded credentials, hosts, or environment values.

## Components & Reuse

- If a component can be reused, build it reusable from the start.
- When planning frontend work, scan the existing component tree (`frontend/src/components/`) first to see what already fits.
- Borrowing a component into another view? Move it to `components/common/`, update both call sites, and test both uses.
- Shared logic goes in custom hooks under `src/hooks/`; shared state in the single Zustand store (`src/store/useStore.js`) with computed getters. No new state libraries.

## Styling

- One stylesheet per domain in `frontend/src/styles/` (`tickets.css`, `dashboard.css`, ...); genuinely shared rules go in `common.css`.
- Every domain sheet is linked from the main stylesheet, with a comment per domain describing what it covers.
- Colors, fonts, and spacing come from the custom properties in `theme.css`; never hard-code a color a variable exists for.
- Inline styles are discouraged — styles live in `.css` files.

## Error Handling

- Routers raise `HTTPException` directly. Services raise their own exception classes; the router catches and converts. Services never import FastAPI.
- Frontend: never call `fetch` directly from components — use `src/api/client.js` via the per-entity module. The client already handles error reporting to `/errors` and request logging; don't duplicate either. Pass an `AbortController` signal for requests tied to component lifetime.

## Testing

- Backend: pytest in `backend/tests/`, using the `conftest.py` factory fixtures (`make_project`, `make_ticket`, ...) over hand-built models. Runs against the separate `lat_test` DB with per-test rollback; don't work around the flock serialization. Run via `./backend/scripts/run_tests.sh` (add `--post --project-id N` to report to the dashboard).
- Frontend: vitest + Testing Library in `src/__tests__/`. Mock with `vi.spyOn()`, clean up in `afterEach`. Run with `npm test`.
- Every new endpoint gets at least a happy-path and a 4xx test; changed components keep their tests green in both old and new call sites.

## Documentation

- Every source file (`.py`, `.js`, `.jsx`, `.css`) carries the standard header block; update `Last Modified` (with the ticket key) on every edit. Format: `docs/rules/global/code-header-format.md`.
- No docstrings by convention — the header carries the what/who-calls-this context. Inline comments only for non-obvious constraints, tagged with the ticket (`# DWB-314: ...`).
- Pydantic schemas use `Create`/`Read`/`Update`/`List` variants and endpoints declare `response_model=`.

## Code Review

- The TL reviews and commits; workers do not commit unless told to.
- Commits: no Co-Authored-By lines, no AI attribution, no model names. DWB ticket keys are fine in this repo's commits, never in external-facing repos.
- Small, one-concern changes; the full suite passes before review is requested.
