# Sprint Warehouse post generator (any project)

Build Miles's biweekly Sprint Warehouse post. The post is HIS, under his name; every
claim gets verified live at draft time (gh/API, never memory). It spans ALL his
projects (IndependenceDay, FRAUDI, portal, apps, whatever exists when it runs): the
archie running the skill generates THIS project's section fully, brackets every other
project's section for its own archie, and Miles hands the doc around until all
sections are real. Iterate with him until he says done, then SAVE (step 6).

## Resolve the project first (no hardcoding)

- Project: `GET http://localhost:8000/api/projects`, match `repo_path` against cwd.
  That gives project_id, prefix, name.
- Repo: `git remote get-url upstream 2>/dev/null || git remote get-url origin` -
  upstream org/repo is the PR search target; the origin fork account is the "Miles
  lane" author filter (confirm against the session-start operator identity).
- Save/load location: `.dwb/sprint-posts/` in THIS repo (create if missing).

## The method (Miles ruling 2026-09-10)

1. **Look back**: what actually happened in the window.
2. **Score the promises**: take the PREVIOUS post's THIS SPRINT GOALS for THIS
   project and mark each DONE (with evidence) or CARRY. Never re-paste old
   accomplishments as new. Carries are labeled "(carried)" in the new goals.

## Steps

### 1. Find last time
Newest `YYYY-MM-DD.md` in `.dwb/sprint-posts/`. Its date anchors the window; its
goals are the scoring target. Empty dir: ask Miles to paste the previous post, save
it, then proceed.

### 2. Window
Previous post date -> today (typically ~two weeks; trust the file date).

### 3. Sweep (all live, in parallel)
- Merged PRs in window on the upstream repo, author = the operator's fork account
  (his lane) AND unfiltered with `--limit 100` for the team-wide count ("100+" if capped).
- `git log --since=<start> --oneline` over this repo's infra/tooling paths.
- `GET /api/projects/{id}/sessions?limit=10` - DWB session headlines in window.
- `GET /api/tl-channel?limit=20` - cross-archie comms in window (feeds other
  projects' brackets and WORKFLOW items).
- Own memory dir entries in window for rulings/milestones that never became PRs.

### 4. Score
Walk the previous post's goals for this project line by line: DONE (PR/date as
evidence, verified against gh) or CARRY. "Was in build" = CARRY, not DONE. Show
Miles the scoring table with the draft.

### 5. Compose (known format - keep exactly this shape)
```
**<PROJECT NAME> - <3-5 word headline of the window>**
- <accomplishment bullets: terse, PR numbers inline, biggest wins first;
   unplanned wins flagged as unplanned>

**<OTHER PROJECT> - [<its archie> to complete: score its previous goals the same
   done-or-carry way]**   (one bracket per other active project; never invent)

**THIS SPRINT GOALS**
**<PROJECT> - <theme>**  (one block per theme; carries marked "(carried)")
**WORKFLOW**  (DWB/tooling items, carried until actually fixed)
**PERSONAL**  (carry verbatim; usually "Play bass")
```
Style: plain copy-pasteable markdown, no blockquote `>` prefixes, hyphens not em
dashes, no icons, DWB ticket keys never in the post (Jira keys / PR numbers fine).

### 6. Save on "done" (MANDATORY - this is "what we had last time")
When Miles says done, write the final text to `.dwb/sprint-posts/<YYYY-MM-DD>.md`
exactly as handed over, brackets included. Confirm the save in one line. If Miles
brings back a version another archie completed, save THAT over yours same-day.

## Notes
- Other projects' sections belong to their archies; bracket-and-route, never fabricate.
- Fleet shipping: this skill is meant to ride deploy-playbooks to every tracked repo
  (Archie_DWB's lane; the recap-auto-generation ask is TL-channel #244, 2026-09-10).
  If DWB ships a server-generated recap, defer to it and retire this.