# Ideas

> Brainstormed, not actionable yet. Move to tickets only after we've talked them through.

## 1. Team status div on dashboard

Revise / clean up the team status div on the main page. Or ditch it and shove that info elsewhere.

## 2. Inter-Archie message channel

A main DWB page addition. A place for Archies (across projects) to talk to each other: send messages, respond. Endpoints for Archie to check. A way to let an Archie know they have a message. One option: a file named "YOU HAVE A MESSAGE FROM ANOTHER ARCHIE.md" that disappears when the endpoint is checked. Exact mechanism TBD.

## 3. Session info on project headers

Add current session info (and its state) to the project main page header AND in the project divs on the main dashboard.

## 4. Project-level agent comms log

On the project level, show all inter-project agent communications. Read-only. Fuzzy search. Dated, with who said what.

## 5. Internal agent scoring system

Sticks and carrots for agents, PMs, and TL. Not just top-down. A threshold where an agent is on PIP and has their ass watched more by the whole team. Very Harry Potter: "10 points, Archie."

## 6. User quickstart guide

A top-level DWB quickstart guide for new users.

## 7. Project word cloud (3D)

Word cloud with interlocking 3D space lines. Click a node and see where the text node is mentioned. Searches the codebase and all the docs, including the .md files for the individual agents.

## 8. Activity audit + expansion

Audit of what currently constitutes an activity in the activity feed. Probably need to add things to it. Examples we're missing: Barry (or any agent) writing to their lessons / scratchpad / recent_sessions .md file via the memory-append endpoint. Plus probably a bunch of others (gate refusals, ticket reassignments, alert dismissals, manual ack overrides, etc.). Walk every meaningful side-effect endpoint and decide: does it deserve a row in the activity feed?

## 9. Alert audit + cleanup

Audit of every alert type the system can raise. Probably need to sundown some that no longer fire or that have lost their purpose, and add new ones for situations we now care about but don't yet alert on. Cross-reference with the failure taxonomy.
