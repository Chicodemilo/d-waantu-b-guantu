---
id: 9
scope: global
---

# Coding standards

The cross-project law. The auditor enforces these on every PR. Project-specific extensions live below the marker in each repo's `CODING_STANDARDS.md` — they add, never override.

**Services.** Logic is farmed out to reusable classes — front end and back end — never embedded in views, routes, or components. When in doubt: `services/` near the top of the tree, class in a subdirectory, named for what it does, usage explained in the file. Look there first when planning new functionality.

**Scripts.** Anything that may run on a server or locally — shell, Python, PHP, seeders, deploys — lives in a top-level `scripts/` directory, documented (what, how to run, from where). Scripts read config from `.env` even when run locally: they get committed, so no hard-coded credentials or environment values.

**Components.** If a component can be reused, build it reusable from the start. Scan the existing component tree before planning new UI. Borrowing a component into another view: move it to `common/`, update both call sites, test both uses.

**Styling.** One style file per domain (login, home, ...) — plain CSS, composed/consolidated CSS, or style tokens alike. Every domain file is linked from the main stylesheet, which carries a comment per domain. Inline styles are discouraged.

**Headers.** Every code file (`.py`, `.js`, `.jsx`, `.css`, shell, and the like) carries the standard header block; `Last Modified` updated on every edit. Markdown docs are exempt.

**Commits.** No Co-Authored-By, no AI attribution, no model names in commit messages or PR text. (Config values like a model id in `.env` files are configuration, not attribution.)

**Tests.** Changed code keeps its tests green in every call site; new endpoints get at least a happy-path and a 4xx test before the ticket closes.
