# CHANGELOG

## 2026-09-30 - Human Memory And Top-Off (sprint 83)

An optional memory model built on the premise that a memory system has to remove things, not just refuse to add them.

- **Four holders, one derived score:** the four are core, scar, working and the journal. New `agent_memories` rows carry a tier (`core`, `scar`, `working`, plus `raw` for the untiered state), a `context_key`, a `fired_count`, and references to the sessions that created and last reinforced them. CORE never fades. A scar decays to a resting floor of 6. A working fact decays to a floor of 1 and is then evicted into the journal. The arithmetic never reaches zero: zero is an eviction state, not a computed score, and nothing leaves memory without being written to the journal first.
- **The score is never stored.** There is no score column and, per the spec, there must never be one. Relevance is a pure function of tier and sessions since the entry last fired, computed at read time in `services/memory_score.py`, which sorts entries into four bands: carried in full at 8-10, compressed to one line at 5-7, flagged as a demotion candidate at 2-4, and a last pass at 1. A derived number cannot drift out of sync with the rule that defines it.
- **The clock counts sessions, not days.** An agent that has not worked in three weeks has forgotten nothing, because nothing happened to it. Decay tracks experience.
- **Encode raw, sort at the boundary:** rows are written untiered during a session with only the tags the moment knows, `cost`, `caught_by` and `surprised`. Tiering in the moment rubber-stamps in-the-moment salience, which is the judgment consolidation exists to make.
- **A journal that costs nothing until you reach for it:** `journal_entries` are append-only, never auto-loaded, and queried by tag and date. Retrieval is logged through a single write site, and the count is permanent and never decays. At three retrievals an entry stops being a story and becomes a rule.
- **One memory or the other, enforced in code:** when `human_memory` is on, the stock store is sealed for writes and for the read that serves an agent its own memory, and a hook (`scripts/hooks/block_harness_memory_writes.py`) seals the harness's own file store. A legacy read path still excerpts the stock file into the spawn bundle and is open as a defect. The failure mode being designed out is not the wrong memory being used, it is two memories that both look authoritative and disagree.
- **Switching modes is a transition, not a flag flip:** `memory_mode` carries `adopting` and `reverting` as real states alongside `stock` and `human_memory`. Adoption snapshots, then walks entries one at a time through `pending`, `proposed`, `decided`, `written`, `skipped` and `journaled`, against a run that is resumable and can be aborted. Reverting renders back to stock and journals whatever will not fit. Nobody is ever handed a whole memory file and asked to sort it out, and nothing leaves memory without landing in the journal first.
- **Top-off, on its own toggle:** a periodic self-check fired by the session runner rather than by an agent choosing to run it, asking whether it is answering a question it already answered, whether the user is getting what they asked for or what the agent decided to give them, and what it is asserting from a summary rather than the source. `topoff_interval` defaults to 10. It is independent of `memory_mode` by design, because repetition and drift are not memory-structure problems.
- **Status: in use on one project, still beta.** `backend/scripts/human_memory_exerciser.py` drove all five movements against the live API on 2026-10-01 and returned PASS 5/5, printing verbatim the text an agent receives. DWB then adopted, one entry at a time: 396 entries across 7 agents, now 360 scars and 36 working facts, with agents served from the tiered store at spawn. Turning it on is what found the defects. Adoption first shipped unreadable, because the writer that creates an adopted row never stamped the session it came from, so every row scored as having no point on the clock and no agent received anything. That is repaired, and nine tickets came out of the night, several of them correctness bugs inside this lane. The fade in particular is designed and unproven: no consolidation run has yet shrunk an agent's memory without a human prompting it, and that remains the bar. Exercising the movements and migrating a corpus are both prompted runs, so neither is evidence for the unprompted case. The mode is versioned (`memory_schema_version`) and stays in beta deliberately, so the schema is free to move.
- Sprint 83, DWB-584 through DWB-597.

## 2026-08-12 — Standards Auditor (sprints 23–24)

The self-enforcing standards-audit system, end to end.

- **Fresh-auditor pipeline:** `scripts/run_standards_audit.sh` → `standards_audit.py` spawns a context-starved headless `claude -p` judged only on the global standards sheet + the repo's `## Project Extensions` + the diff, against a strict-JSON contract. Malformed output is never posted.
- **Storage + API:** new `standards_audit` table and `/api/standards-audits` (record verdict/violations/scorecard), plus an explicit idempotent `/{id}/apply-scorecard` that writes to the `score_event` ledger (`source=audit`, `audit_grant`/`audit_demerit`, bypassing peer caps).
- **The_Auditor** system agent (id 51, `project_id` NULL) seeded via migration dwb028; owns audit ledger rows and activity-feed attribution.
- **Visibility:** every audit raises an alert (info=pass, warning=reject) + feed entry; new **Audits page** at `/projects/:id/audits` with pass/fail stats and expandable rows; shared verdict/violations/scorecard components under `components/common/`.
- **Gate:** `force_standards_audit` blocks sprint close without a passing audit in-window. `force_coding_standards_md` (doc-exists) enabled across projects.
- **Token attribution fix (DWB-022):** per-ticket token writes are now atomic (ledger event + cache in one commit), attributed via `X-Agent-ID`/assignee, with a real `token_source`. Migration dwb022 reconciled 10 orphan tickets (~550k phantom tokens → `source='reconciled'`).

## 2026-04-09 — BREAKING: Directory + Repo Rename

### READ THIS FIRST IF ANYTHING LOOKS WRONG

**The project has been renamed everywhere.**

| What | Before | After |
|------|--------|-------|
| **Directory** | `/Users/mchick/Dev/local_agent_tracker` | `/Users/mchick/Dev/d-waantu_b-guantu` |
| **GitHub repo** | `MilesVTG/local-agent-tracker` | `MilesVTG/d-waantu-b-guantu` |
| **Claude project dir** | `~/.claude/projects/-Users-mchick-Dev-local-agent-tracker` | `~/.claude/projects/-Users-mchick-Dev-d-waantu-b-guantu` |

**Why:** Agents were confusing the app name (D'Waantu B'Guantu / DWB) with
the old directory name (local_agent_tracker). The directory name now matches
the application identity.

### If you are an agent mid-session and your working directory is gone

Your `cwd` pointed at `/Users/mchick/Dev/local_agent_tracker` which no
longer exists. Here's what to do:

1. **Stop what you're doing** — any file writes to the old path will fail
2. **Re-orient:** the repo is now at `/Users/mchick/Dev/d-waantu_b-guantu`
3. **Update your git remote** if needed:
   ```bash
   git remote set-url origin https://github.com/MilesVTG/d-waantu-b-guantu.git
   ```
4. All code, branches, history, and database are intact — only the paths changed

### What did NOT change

- **MySQL database name** remains `local_agent_tracker` — this is the DB name, not the app name
- **DWB project prefix** remains `DWB`
- **All API endpoints, ports, and behavior** are unchanged
- **Docker containers** (`lat_mysql`, `lat_phpmyadmin`) are unchanged
- **All branches and git history** are preserved

### Files updated in this rename

- `seed.sql` — repo_path
- `backend/scripts/attribute_tokens.py` — transcript dir matching (legacy patterns kept as fallback)
- `backend/app/services/sync_check.py` — MEMORY_DIR path
- `docs/team_lead_playbook.md` + `.claude/team_lead_playbook.md` — repo_path examples
- `README.md`, `PLAN.md`, `QUICKSTART.md`, `ARCHITECTURE.md` — directory references

### If you have stale references in your context

Search for `local_agent_tracker` or `local-agent-tracker` and replace
path references with `d-waantu_b-guantu` / `d-waantu-b-guantu`.
