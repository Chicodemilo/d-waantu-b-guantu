# Doc audit backlog

Standing reconnaissance over the doc layer (DWB-639), opened 2026-10-07. A living
punch list, not a fix list. Items are not fixed here.

**Every item below was verified against the code, a live API call, or the
database.** Nothing in this file was confirmed by reading another doc, because a
doc agreeing with a doc is how the DWB-638 class survives twenty days. Where a
claim was checked and found correct, it is recorded under § Checked and correct
rather than dropped, so the next pass does not spend a day re-deriving it.

Line numbers are cited per file, against the working tree of 2026-10-07. A
`docs/` playbook and its deployed `.claude/` twin are not byte-identical by
design, so a diff between the pair is not evidence of drift, and both are cited
separately where both are wrong. That tree carries DWB-638's edits to the three
playbooks and `session_lifecycle.md` uncommitted, so if those are revised in
review the citations into those four files move; every other citation is against
committed content.

## Tier 1: a reader acting on this does the wrong thing

### 1. `docs/human_memory_spec.md:11` says the feature is not built. It is in production.

- **Claim:** `> Status: spec handed off, ticket slate awaiting approval. Not built.`
- **True:** shipped and authoritative on two live projects.
- **Verified:** `GET /api/projects` reports `memory_mode=human_memory` on IND and
  DWB. `GET /api/agents/28/memory/scored` returns 200 with a populated store.
  `POST /api/agents/{id}/memories` is the write path DWB agents use today. Eight
  files under `backend/app/` cite this spec by section as their authority
  (`models/agent_memory.py`, `models/journal_entry.py`, `models/project.py`,
  `routers/agents.py`, `services/memory_mode.py`, `services/memory_score.py`,
  `services/project.py`, `services/raw_memory.py`).
- **Why tier 1:** this is the canonical document the implementation defers to,
  and its first screen tells the reader none of it exists. Anyone opening it to
  settle a question about live behaviour stops at the header.

### 2. `.claude/project_rules_worker.md:233` sends workers to a tool this project forbids.

- **Claim:** "Tickets created via `dwb2jira create proposal.yaml` (see PM/TL
  playbook). Don't `POST /api/tickets` directly."
- **True:** DWB has no Jira link, so `dwb2jira` has nothing to talk to, and the
  DWB API is the only path.
- **Verified:** `GET /api/projects/1` returns `jira_base_url=None`,
  `jira_project_key=None`. The deployed `.claude/worker_playbook.md:1-3` banner,
  written by the deploy transform from that same null, says the opposite in as
  many words: "Do not invoke `dwb2jira` tools", "All ticket transitions go
  through the DWB API directly."
- **Why tier 1:** two files a worker reads at spawn give opposite instructions
  about the same action, and `project_rules_*` survives deploy untouched, so
  this one never self-corrects.

### 3. Three files describe `GET /api/projects/{id}/gate-status` as covering gates it does not return.

- **Claims:**
  - `CLAUDE.md:99` "Live list: `GET /api/projects/{id}/gate-status`. Nine
    boolean gates (test run + coverage, four `*_md` doc-exists checks,
    `force_standards_audit`, `force_headers`, `force_consolidation`)"
  - `docs/team_lead_playbook.md:194` "Gate status | `GET
    /api/projects/{id}/gate-status` | Doc gates + consolidation."
  - `README.md:122` "Check gates: `GET /api/projects/{id}/gate-status`", printed
    directly under a ten-row gate table.
- **True:** the endpoint returns six entries: four `*_md` doc gates,
  `force_headers`, `force_standards_audit`. It does not report
  `force_test_run`, `force_test_coverage` or `force_consolidation`, all three of
  which sprint close does enforce.
- **Verified:** live `GET /api/projects/1/gate-status` returns exactly those six
  toggles. `backend/app/routers/projects.py:676` `_DOC_GATES` holds four
  entries; the headers and audit blocks are appended beside it; nothing else is.
  `backend/app/services/sprint.py` enforces nine: `force_test_run` (245),
  `force_standards_audit` (267), `force_test_coverage` (284), the four doc gates
  (296-299), `force_headers` (313), `force_consolidation` (327). `gate-status`
  carries no entry for the three it omits.
- **Why tier 1:** a TL told the endpoint covers consolidation, checking it
  before close, reads green on a gate the endpoint never looked at. The TL
  playbook also contradicts itself here: § 5a correctly sends you to
  `GET /api/projects/{pid}/consolidation-status` for that gate.

### 4. `CLAUDE.md:99` and `README.md:107` say all sprint gates default OFF. One defaults ON.

- **Claim:** "all default OFF" / "All default OFF (opt-in per project)".
- **True:** `force_handoff_md` defaults to `True`.
- **Verified:** `backend/app/models/project.py:120`,
  `force_handoff_md: Mapped[bool] = mapped_column(Boolean, nullable=False,
  default=True)`. Every other `force_*` column on lines 115-129 is
  `default=False`.
- **Note:** `.claude/project_rules_worker.md:51` already states the correct
  version ("`force_handoff_md` defaults to True") and explains the test
  consequence. So this is a two-against-one contradiction in which the minority
  file is the right one.

### 5. `CLAUDE.md:126` and `README.md:132` give a failure taxonomy whose values do not exist.

- **Claim:** "Failure types: A-G (manual taxonomy), rework, test_failure" /
  "**Manual taxonomy:** types A-G, categorized by the PM."
- **True:** the seven manual values are `context_degradation`, `spec_drift`,
  `sycophantic_confirmation`, `tool_selection_error`, `cascading_failure`,
  `silent_failure`, `integration_failure`. "A-G" is a count of categories, never
  a value any row holds.
- **Verified:** `GET /api/failure-records/summary` over 19 live records returns
  `rework` 15, `test_failure` 3, `integration_failure` 1, and nothing else.
  `backend/app/models/failure_record.py:38` types the column as a free
  `String(50)` with no enum, so a literal `"A"` would be accepted and would
  match nothing.
- **Note:** `docs/pm_playbook.md:392` and `ARCHITECTURE.md:451` both carry the
  seven real values. CLAUDE.md is the one auto-loaded by every agent and it
  carries only the letters.

## Tier 2: misleading, but a careful reader recovers

### 6. `GET /api/journal` is documented nowhere an agent reads.

- **True:** the search endpoint exists, takes `agent_id`, `tags`, `date_from`,
  `date_to`, `term`, `limit`, and REFUSES a read that narrows nothing with 422:
  "the journal is never read whole. Supply at least one of tags, date_from,
  date_to, term... agent_id alone does not narrow a read, it only scopes one."
- **Verified:** live. `GET /api/journal?limit=1` -> 422,
  `GET /api/journal?agent_id=28&limit=1` -> 422, parameter list read off
  `/openapi.json`.
- **Gap:** all three playbooks document only `POST /api/journal`
  (`worker_playbook.md:164`, `pm_playbook.md:89`, `team_lead_playbook.md:52`).
  The read shape appears in exactly one place, the
  `STOCK_MEMORY_SEALED_POINTER` string in
  `backend/app/services/memory_mode.py`, which only an agent on a sealed project
  with no scored memory ever sees. An agent wanting to search its own episodes
  has no documented way to, and a guessed call 422s.

### 7. `.claude/project_rules_worker.md:195` names three memory files that no longer exist.

- **Claim:** "`POST /api/agents/{id}/session-complete` - append timestamped entry
  to scratchpad/lessons/recent_sessions".
- **True:** DWB-401 collapsed those into a single `memory.md`, and DWB-560 made
  `session-complete` write only the lessons list. On a `human_memory` project
  the route is sealed at 409 entirely.
- **Verified:** `backend/app/services/agent_memory.py:32`,
  `_AGENT_OWNED_FILES = ("memory.md",)`; the scaffold writes `identity.md` and
  `memory.md` and nothing else. `backend/app/services/memory_mode.py`
  `_WRITE_REPLACEMENT` lists `session-complete` as sealed.
- **Assigned elsewhere:** the sealed half is DWB-638, already in review. The
  three dead filenames are not, and are not fixed by it.

### 8. Root docs claim 149 endpoints across 25 routers.

- **Claims:** `README.md:214` "149 endpoints across 25 routers",
  `ARCHITECTURE.md:148` "149 endpoints, 25 routers", `ARCHITECTURE.md:132` "25
  router files", `CLAUDE.md:174` "the full 149-endpoint reference".
- **True:** 137 distinct paths, 174 method-plus-path operations, 30 tag groups,
  30 router files on disk. Neither reading of "endpoints" is 149.
- **Verified:** `/openapi.json` counted directly;
  `ls backend/app/routers/*.py | grep -v __init__ | wc -l` returns 30.
- **Why tier 2 rather than tier 3:** a reader who believes the reference is
  complete stops looking for the route they need. Four separate files repeat it,
  so it also sets the pattern for the next counter.

### 9. Peer-scoring caps are stated as one combined allowance; the code has two separate ones.

- **Claim:** `worker_playbook.md:409` "you may dock or grant any one peer at most
  10 total per sprint", and the same sentence in `pm_playbook.md:416` and
  `team_lead_playbook.md:587`.
- **True:** `MAX_DING_PER_TARGET_PER_SPRINT = 10` and
  `MAX_GRANT_PER_TARGET_PER_SPRINT = 10` are independent budgets, checked in
  separate branches. An agent may dock a peer 10 AND grant that peer 10 in one
  sprint, bounded only by the shared 20 influence.
- **Verified:** `backend/app/config/scoring.py:59-60`;
  `backend/app/services/scoring.py:450` and `:457` are two separate comparisons.
- **Why it matters at all:** the sentence reads as a vendetta cap half the size
  of the real one, which is the direction that makes an agent withhold a
  legitimate carrot.

## Tier 3: stale labels and counters, no action taken on them

### 10. `.claude/project_rules_worker.md:7` says "Five steps", then lists four.

- **True:** `docs/worker_playbook.md` § On Spawn: Identity has four numbered
  steps (identify, cache `agent_id`, TL writes the session marker, memory is
  already in your prompt).
- **Verified:** counted in the source file.
- **Also:** the four items project_rules lists are not the four the playbook
  has. It substitutes "follow the spawn-time read order", which is a different
  section, for the memory step.

## Checked and found CORRECT

Recorded so the next pass does not re-verify them. Each was checked by the means
named, not by reading a second doc.

- **Every `/api/...` path cited anywhere in the doc layer resolves.** 83 distinct
  paths across `docs/`, `.claude/project_rules_*`, and the root docs, normalised
  and matched against `/openapi.json`. The seven non-matches are prose or file
  paths (`/api/tickets/CI-217` as an example key, `/api/client.js` as a source
  file, `/api/tracking/` and `/api/hooks/` as prefixes), not endpoint claims.
- **Every documented HTTP method matches the live route.** 260 method-plus-path
  pairs checked; one apparent miss, `team_lead_playbook.md:170`, is the
  shorthand "`POST/PATCH /api/tickets`" and is not an error.
- **`docs/session_lifecycle.md:89-96` close_method table is complete and
  accurate.** All six values present, including `idle_timeout`, and
  `ai_classifier` is correctly marked retired. Matches `DwbCloseMethod` in
  `backend/app/models/dwb_session.py:49-63`. `DwbOpenMethod` correctly has no
  `idle_timeout`, and `worker_playbook.md:57` correctly calls it close-only.
- **`team_lead_playbook.md:199` on the sessions list is right, and stricter than
  it says.** "No status query param yet; filter client-side for `closed_at IS
  NULL`" holds: `?status=open` returns 400, not a silent ignore, with the body
  "unknown query param(s) status; valid params: limit, offset". Confirmed
  against the declared parameters in `/openapi.json`.
- **Peer-scoring magnitudes are correct in all three playbooks.** 20 influence
  per sprint, a single demerit removing at most 5. Matches
  `backend/app/config/scoring.py:49` and `:58`. Only the per-peer phrasing is
  wrong, see item 9.
- **`force_team_md` is genuinely gone.** `.claude/project_rules_worker.md:74`
  says the column was dropped in DWB-321 and must not be referenced; no
  occurrence survives anywhere under `backend/app/`.
- **The failure taxonomy in `docs/pm_playbook.md:392` and `ARCHITECTURE.md:451`
  is complete.** All seven manual values plus the two auto-detected ones, and
  `integration_failure` (the only manual value with live rows) is present in
  both. The problem in item 5 is confined to CLAUDE.md and README.

## Already assigned, left alone

- **The four sealed memory routes taught across the playbooks and the generated
  spawn block.** DWB-638, in review 2026-10-07. Covers
  `docs/{worker,pm,team_lead}_playbook.md`, `docs/session_lifecycle.md:85`, and
  `backend/app/config/memory_rules.py`. Not re-listed above.
- **Stick redemption unreachable under `human_memory`.** Found during DWB-638,
  reported to the TL for its own ticket. `services/stick_redemption.py` parses
  its trigger token only out of a `memory/append` body, and that route is
  sealed; `POST .../memories` has no redemption call. Documented as working in
  all three playbooks, now carrying a negative statement pending the fix.

## Method, so this is re-runnable

Two mechanical sweeps, then a read.

1. **Path resolution.** Extract every `/api/...` token from the doc layer,
   normalise `{anything}`, `:param` and literal ids to a single placeholder,
   match against `/openapi.json`. Finds the "endpoint does not exist" class.
2. **Method resolution.** Same, but capture the HTTP verb preceding the path and
   check it against the operations declared for that path. Finds the "endpoint
   exists, verb does not" class, which sweep 1 structurally cannot see.
3. **The read.** Everything in tiers 1 and 2 above except items 6 and 8 came out
   of reading the role files against each other, not out of either sweep. Both
   sweeps return clean on a doc that confidently describes the wrong behaviour
   of a route that exists, which is most of what is actually wrong.

The limit worth stating: a sweep that checks existence cannot check meaning, and
every tier 1 item here is a meaning error on a route that resolves perfectly.
