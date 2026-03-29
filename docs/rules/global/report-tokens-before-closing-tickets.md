---
id: 10
scope: global
---

# Report tokens before closing tickets

Before marking a ticket done, report your token usage: POST /api/tickets/:id/tokens with {"tokens_used": N, "time_spent_seconds": N}. If you forget, an alert will remind you.
