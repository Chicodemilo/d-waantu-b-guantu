> THIS PROJECT IS NOT LINKED TO JIRA.
> Do not invoke `dwb2jira` tools or reference Jira issue keys.
> All ticket transitions go through the DWB API directly: `PATCH /api/tickets/{id}` with `{"status": "..."}` and the `X-Agent-ID` header.

# Coding standards

The cross-project law. The auditor enforces these on every PR. Project-specific extensions live below the marker in each repo's `CODING_STANDARDS.md` — they add, never override.

**Services.** Logic is farmed out to reusable classes — front end and back end — never embedded in views, routes, or components. When in doubt: `services/` near the top of the tree, class in a subdirectory, named for what it does, usage explained in the file. Look there first when planning new functionality.

**Scripts.** Anything that may run on a server or locally — shell, Python, PHP, seeders, deploys — lives in a top-level `scripts/` directory, documented (what, how to run, from where). Scripts read config from `.env` even when run locally: they get committed, so no hard-coded credentials or environment values. (Non-secret fixture identifiers — e.g. seeded `api_key` labels — are data, not credentials; deterministic migrations may embed them.)

**Components.** If a component can be reused, build it reusable from the start. Scan the existing component tree before planning new UI. Borrowing a component into another view: move it to `common/`, update both call sites, test both uses.

**Styling.** One style file per domain (login, home, ...) — plain CSS, composed/consolidated CSS, or style tokens alike. Every domain file is linked from the main stylesheet, which carries a comment per domain. Inline styles are discouraged.

**Headers.** Every code file (`.py`, `.js`, `.jsx`, `.css`, shell, and the like) carries the standard header block; `Last Modified` updated on every edit. Markdown docs are exempt.

**Commits.** No Co-Authored-By, no AI attribution, no model names in commit messages or PR text. (Config values like a model id in `.env` files are configuration, not attribution.)

**Tests.** Changed code keeps its tests green in every call site; new endpoints get at least a happy-path and a 4xx test before the ticket closes.

---

## Project Extensions

_Project-specific additions below; they add to the global sheet, never override it._

**Stack.** Backend: Python 3 / FastAPI / SQLAlchemy 2.0 / Alembic / MySQL. Frontend: JavaScript (not TypeScript) / React 18 / Vite. Plain CSS off `frontend/src/styles/theme.css` variables, linked through `styles/index.css`. Deliberately no linter/formatter configs - match the surrounding code; don't reformat wholesale.

**Backend shape.** Typed Python everywhere (`int | None` style); no docstrings by convention - the file header carries the what/who-calls-this context. Thin routers; business logic in `app/services/`; Pydantic schemas as `Create`/`Read`/`Update`/`List` variants with `response_model=` declared. Services raise their own exceptions; routers convert to `HTTPException`.

**Migrations.** Hand-written only (MySQL autogenerate is not trusted). Revision ids follow `dwbNNNa1b2c3` after the ticket; single head; migrations carry the standard code header.

**Frontend shape.** Single Zustand store (`src/store/useStore.js`); never raw `fetch` in components - go through `src/api/` modules over `src/api/client.js` (it already handles error reporting and request logging); shared logic in `src/hooks/`; shared client services in `src/services/`.

**Tests.** Backend: pytest with the `conftest.py` factory fixtures against the `lat_test` DB (per-test rollback; respect the flock - a hung-looking suite is another run in progress). Run `./backend/scripts/run_tests.sh` (`--post --project-id N` to report to the dashboard). Frontend: vitest + Testing Library in `src/__tests__/`.

**Review & commits.** The TL reviews, audits (scripts/run_standards_audit.sh on the staged batch), and commits; workers never commit. DWB ticket keys are fine in this repo's commits, never in external-facing repos.
