# Project Rules — Team Lead

> Project-specific rules for the TL. This file is NOT overwritten by deploy.
> Last verified against the API: 2026-11-10.

## Resolve Your Own Ids — Never Read Them Off A Page

**This file names no project id, no agent id and no counters, on purpose.** Two machines
run DWB against two separate MySQL instances, both named `local_agent_tracker`, both on
`localhost:8000`, both checkouts of this repo. The ids are different in each and nothing
in an API response tells you which one you reached. A written-down id is therefore wrong
roughly half the time, and the failure is silent: on one box the id that means DWB means a
completely different project on the other, so trusting it files DWB work into someone
else's board under someone else's agent.

Resolve at startup, every session, in this order:

```bash
# 1. your project: match the repo you are actually sitting in, not the prefix
curl -s localhost:8000/api/projects | python3 -c "
import sys,json,os
rows=json.load(sys.stdin)
me=[p for p in rows if p.get('repo_path')==os.getcwd()]
print(me[0]['id'], me[0]['prefix'], me[0]['memory_mode'])"

# 2. your agent id (and everyone else's)
curl -s -X POST localhost:8000/api/agents/identify -H 'Content-Type: application/json' \
  -d '{"role":"team-lead","name":"Archie_DWB","project_prefix":"DWB"}'
curl -s localhost:8000/api/projects/$PID/team
```

`repo_path` is the only field that distinguishes the two environments, which makes it the
only safe key. Matching on `prefix == DWB` alone finds a row on both boxes.

The same applies to every count in this file's history — sprint numbers, ticket numbers,
max ids. They are not written here because they are stale the day after they are written.
Query them.

## DWB Project Context

- **Repo:** whichever checkout you are in. **Prefix:** `DWB`. **DB:** `local_agent_tracker`
  (legacy, don't change).
- **No Jira** — `jira_base_url` is null, so ticket writes refuse `jira_issue_key`. Never
  invoke `dwb2jira` here.
- **`memory_mode` is per-project and the two environments differ. Read it** (step 1 above)
  before your first memory write:
  - `stock` — the stock memory API is live: `memory/append`, `session-complete`,
    `memory/compact`, `memory/condense`. `append` requires `{"file":"memory","content":…}`;
    omitting `file` is a 422.
  - `human_memory` — stock memory is SEALED, all four of those return 409. Lessons go to
    `POST /api/agents/{id}/memories`, which requires `body`, `condensed` (one line carrying
    THE LESSON, not the setup), `keywords` and `situation` (one line naming the moment the
    lesson applies). Keywords are matched against that situation with retrieval's own
    comparison, so one your sentence does not contain is refused; a keyword of ordinary
    words naming no subject (`before i`, `every agent`) is refused separately, because it
    fires on any prose. Episodes go to `POST /api/journal`. Applies to the TL too.
- **`runs_own_tests`** is not a column: `app/config/server_repo.py::runs_own_tests` derives
  it by matching a project's `repo_path` against the repo this server's own code runs from.
  It is true for whichever checkout is serving, and `POST /api/system/run-tests` refuses
  every other project.

## TL Behavioral Rules

- **Never write code or edit files directly.** Delegate ALL implementation to workers, then review. Exceptions: `HANDOFF.md`/`ARCHITECTURE.md`/`README.md`, `.claude/*` (only the TL can edit those safely), and the user-signalled small-change path in the playbook § 4c.
- **Never shut down teams** unless the user explicitly asks. Sprint close and idle teammates are not shutdown signals.
- **Always re-deploy playbooks** to active projects after committing changes to `docs/`. Deploy copies current state — commit without deploy leaves other projects stale. Deploy reports a list whether or not the bytes changed; verify on disk afterwards.
- **Ticket display (non-Jira):** `| DWB # | Sprint | Title | Owner | Status |`. One row per ticket, `—` for empty, current project only. The 8-column Jira layout in `.claude/pm_playbook.md § Ticket Display Format` does NOT apply here.
- **Pam handles status updates and registrations** when spawned. With <3 parallel workers there is no PM and the TL files directly.

## Team Composition (DWB)

Roster is DB-authoritative — `GET /api/projects/{your_id}/team`. **The agent ids collide
between the two environments**: the same integer is the team lead on one box and a backend
worker on the other, so an `X-Agent-ID` copied from anywhere but a live `identify` or
`/team` call attributes your work to someone else.

Canonical names on this project, ids resolved at runtime:

| Role | Name |
|------|------|
| team-lead | Archie_DWB |
| pm | Pam_DWB |
| backend-worker | Barry_DWB (Stan as second) |
| frontend-worker | Freddie_DWB |
| system-ops | Sylvie_DWB |
| tester | Sage_DWB |
| docs-writer | Dolores_DWB |

A roster row is registration, not a live process — CC teams do not survive a session.
Whether a given name is on the roster at all differs between environments; `/team` is the
answer, not this table, which is the naming canon.

## Architecture — Two Playbook Layers

1. **`docs/` = deployable playbooks** — generic, pushed to other projects via deploy-playbooks. Overwritten on every deploy.
2. **`.claude/agents/` = local agent defs** — Claude Code teammates in THIS repo only. Not deployed.
3. **`.claude/project_rules_*.md` = project-specific rules** — created blank on deploy, never overwritten. Each agent reads theirs on startup. Never overwritten by deploy, but still tracked: a `git pull` carries the other environment's version in.

## Sprint Conventions

- One active sprint, one in-progress epic — DB-enforced, a second returns 409.
- Sprint names descriptive (from goal), not "Sprint N".
- **Gates enabled differ per environment.** Read `GET /api/projects/{your_id}/gate-status`; do not trust a list written down. `all_passing` is three-valued: `null` means a gate could not be evaluated, NOT that one failed. `force_team_md` was removed in DWB-321 (roster is DB-authoritative).
- Always-on close gates independent of toggles: write-on-close memory (DWB-519) and the failure-record review.

## Key Patterns Learned

- Alembic autogenerate can't detect MySQL enum changes — write manual migrations for ALTER TYPE.
- Frontend vitest has pre-existing mock failures — known, not blocking.
- Team Status panel is ticket-status driven (deterministic) — no hooks or registration needed.
- Adding a new doc gate is 4-point wiring (model, schema, router `_DOC_GATES`, sprint close loop) + `_DOC_FILES` + seed demo.
- Behaviour rules have a second home in code generators (`agent_memory.py`, `config/memory_rules.py`) and go stale silently — grep those when a behaviour ticket lands.
- Run one-off DB scripts from `backend/` (cwd-relative `.env`), and restart uvicorn after a pull — `--reload` does not reliably fire on a 250-file pull, and it then serves pre-pull code with a healthy `/api/status`. Check `openapi.json` for a route you know landed.
- `docker compose exec mysql mysql -uroot -proot` fails with access denied here; creds are `MYSQL_USER`/`MYSQL_PASSWORD` in the repo-root `.env`. A swallowed auth error looks exactly like an empty result — always run a positive control.
