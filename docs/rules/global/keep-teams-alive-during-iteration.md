---
id: 4
scope: global
---

# Keep Teams Alive During Iteration

Don't shut down teams after a batch of tasks completes. Keep them alive while the user is actively iterating.

**Why:** User wants to give ongoing fixes and have the lead parcel them out to workers. Spinning down and back up wastes time and tokens.

**How to apply:** Only shut down a team when the user explicitly says they're done, or when switching to a completely different workflow. Default to keeping teams running during active development sessions.
