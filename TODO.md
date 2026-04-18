# TODO

## Seed data — slim down the generic seeder

`seed.sql` currently populates a full demo universe: 4 projects (DWB, INGEST, RECON, DOCS), 13 agents, 7 epics, 5 sprints, 19 tickets, plus related rows. This is too much for a generic "fresh install" seed.

**Problem:** the DWB project itself shouldn't be in the shared seeder. It's Miles's personal project, not something every clone should come pre-populated with. Same goes for the other placeholder projects — they exist only to make the dashboard look populated.

**Direction:**
- Split seed data into two files:
  - `seed_demo.sql` — a minimal "touring" dataset (1 project, a couple agents, one sprint, a few tickets) used only for QUICKSTART / demo walkthroughs.
  - `seed_personal_dwb.sql` (gitignored or kept out of repo) — Miles's personal DWB project rows, for his own dev setups.
- Update QUICKSTART.md step 5 to reference the demo seeder.
- Don't ship a seeder that pre-loads any project named after this repo itself — it's confusing for newcomers and it creates noise on first run.

**Related:** the current seeder also had several columns missing (`epic_id` on sprints, force_* booleans on projects) that only failed because strict mode + missing defaults. Already fixed in commit 8a39341 — defaults added to migrations and `epic_id` added to the sprints INSERT. The slim seeder should still be validated against the fixed schema.
