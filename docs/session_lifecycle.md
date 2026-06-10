# DWB Session Lifecycle

> User-facing reference for the DWB session model. How sessions open, how they close, what gets rolled up, and how to think about them across multiple projects.

## What is a DWB session

A DWB session is a user-bounded span of work on a project. It begins when you signal that you want to start working with the team and ends when you signal that you want to stop. Everything that happens in between - across however many Claude Code sessions, however many subagents, however many tickets - is rolled up under that one DWB session.

Important distinction: a DWB session is NOT a Claude Code session. Claude Code spawns a new session every time you open a window, run a slash command, or spawn a subagent. Those are short-lived and noisy. A DWB session is the *intent boundary* the human user draws around all of that activity.

One DWB session typically spans many CC sessions:
- The TL's main window
- Each spawned worker (Pam, Barry, Freddie, etc.)
- Any one-off subagents (Explore, etc.)

The system uses Claude Code hooks to attribute each CC session's tokens and time to the DWB session that was open at the moment. You never have to think about it; just open and close.

### Single-active rule

At most one DWB session is open per project at any time. This is enforced at the database level - you cannot accidentally have two opens on the same project. (Multiple projects can have parallel opens; see "Multi-project" below.)

## Opening a session

You open a session by saying something the TL recognizes as an open phrase. The detection runs in two layers:

**Layer 1 - regex fast path.** A small catalogue of common phrases is matched directly on every user prompt. When one hits, the system opens the session before the TL has even read your message. Examples that fire the regex layer today:

- `you are archie, read the playbook`
- `you are archie, read your playbook`
- `you are <name>, you are team lead, read the playbook`
- `you are <name>, read the handoff and playbook`
- `read your handoff and playbook`
- `open a dwb session`
- `open the session`

The full list lives in `backend/app/config/session_phrases.py`. Matching is case-insensitive and tolerates extra whitespace; the `<name>` slot accepts any single alphanumeric token (so `you are zelda, read the playbook` works the same way).

**Layer 2 - TL reasoning.** When you say something that *means* open but isn't in the regex catalogue, the TL evaluates the message and acts:

- Confident: the TL opens the session and announces it ("Opened DWB session 47.").
- Ambiguous: the TL asks one short clarifying question first. If you confirm, the session opens and is tagged so the dashboard knows the AI layer caught it.
- Irrelevant: most messages. The TL does nothing.

### How the open is recorded

Every open is tagged with an `open_method` so the dashboard can show which layer is doing the work:

| `open_method` | Meaning |
|---|---|
| `regex` | Layer 1 caught it on a hook (instant) |
| `ai_confident` | Layer 2 - TL acted without asking |
| `ai_asked` | Layer 2 - TL confirmed with you first |

For regex-method opens, the matched catalogue phrase is recorded on the row (it comes from the hardcoded list in `session_phrases.py`, not free-form user text). For AI-layer opens, only the `open_method` enum is kept; the user's literal message is never persisted.

## Closing a session

Same two-layer model, in reverse. You signal you want to stop, and the system closes the session.

**Layer 1 phrases** (regex catalogue, current list):

- `have the team write docs and exit`
- `team write docs and exit`
- `write docs and exit`
- `close the session`
- `close this session`
- `close the dwb session`
- `shut it down for the night`
- `shut it down`
- `wrap it up for the night`
- `wrap up for the night`
- `end of session`
- `that's a wrap`

**Layer 2** - TL reasoning again. Confident close = act + announce ("Closing DWB session 47 (84,232 tokens, 2h 14m)."). Ambiguous = ask one question. Irrelevant = ignore.

**Idle auto-close.** If you forget to close, the system catches it. A background sweeper runs every minute or so, and any open session whose last activity is older than 60 minutes (the default) auto-closes. The session is tagged `close_method=idle_timeout`, `close_reason=idle` so the dashboard can distinguish a forgotten close from an explicit one.

**Optional headline (planned, DWB-346).** The close endpoint will accept an optional `headline` field (80-char cap) so the TL can pass a short summary at close time, e.g. "Layer-1 regex fix" or "Frontend session panel". When omitted, the dashboard falls back to an auto-derived summary like "epic-name (N tickets done)". Additive; current closes that don't pass it keep working unchanged.

### How the close is recorded

| `close_method` | Meaning |
|---|---|
| `regex` | Layer 1 phrase match on a hook |
| `ai_confident` | Layer 2 - TL acted without asking |
| `ai_asked` | Layer 2 - TL confirmed with you first |
| `idle_timeout` | Background sweeper closed an inactive session |

Plus a `close_reason`:

| `close_reason` | Meaning |
|---|---|
| `explicit` | You asked to close (regex or AI layer) |
| `idle` | Sweeper closed it after the idle threshold |
| `manual` | Operator closed it directly via the API |

## What gets tracked

When the session closes, two numbers are rolled up onto the session row:

- **`total_tokens`** - the sum of `total_tokens` across every Claude Code hook session that was linked to this DWB session. That covers the TL's main window plus every spawned worker plus every subagent. Pre-link history (work done before the link was wired) does not contribute; the rollup only counts hook sessions that were tagged to this DWB session.
- **`total_time_seconds`** - wall-clock time from `opened_at` to `closed_at`. Not "active typing time"; the full span.

The session detail endpoint (`GET /api/sessions/{id}`) also exposes breakdowns:

- **`by_role`** - tokens grouped by agent role (team-lead, pm, backend-worker, frontend-worker, tester, docs-writer, etc.).
- **`by_ticket`** - tokens grouped by the ticket that was being worked. Tickets are attributed using the same priority the tracking system uses elsewhere: in_progress > todo > in_review > recently done.
- **`overhead`** - tokens that landed in the TL, PM, or Ad Hoc overhead buckets (coordination time + small-fix work without a filed ticket; not ticket-attributed work).
- **`live`** - whether the session is currently open and what its running tallies look like.

There are three overhead buckets:

- **TL overhead** - team-lead coordination, orchestration, review.
- **PM overhead** - PM monitoring, sprint hygiene, comment writing.
- **Ad Hoc** (shipping in DWB-353) - worker session tokens for small fixes the user waived the ticket workflow on (see the skip-ceremony rule in the TL playbook). Before DWB-353, these tokens fired an unattributed alert; now they route to the bucket automatically.

**Computed aggregates (planned, DWB-346/347).** The dashboard's Recent Sessions strip will also show `tickets_made`, `tickets_completed`, `agents_active`, `open_method`, and `close_method` per session. These are derived automatically from existing tracking data - no extra signaling from the user or workers is needed.

## Multi-project

Sessions are scoped per project. The single-active rule applies *per project*, not globally.

In practice this means you can have:

- `Archie_DWB` running on the DWB repo with an open DWB session
- `Archie_CI` running on the CI repo with its own open DWB session
- ... in parallel, with no conflict

Each open phrase resolves to the project whose `repo_path` matches the current working directory. The two sessions roll up independently; tokens and time don't cross-contaminate.

When you spawn a TL like `Archie_DWB` while another project's TL is running, you're not opening a second DWB session on DWB - you're opening one on whichever project that TL belongs to.

## FAQ

**I forgot to close. Now what?**

Nothing breaks. The idle sweeper closes it for you after 60 minutes of inactivity. The session is marked `close_method=idle_timeout`, `close_reason=idle` so the dashboard can show it was an auto-close rather than an explicit one.

If you want to close it manually later, hit `POST /api/sessions/{id}/close` with `close_method=ai_confident` and `close_reason=manual` to record an operator close cleanly.

**I tried to open two sessions at once on the same project. What happens?**

The second open fails with HTTP 409 and the response tells you which session is already active (id + opened_at). The TL silently treats this as a noop - the existing session keeps running.

If two opens race each other (regex layer and AI layer firing on the same message), the database UNIQUE index guarantees only one wins; the loser noops cleanly.

**What counts as "token spend" in the total?**

Every Claude Code hook session that ran during the DWB session and was linked to it. That's the TL's tokens, every worker's tokens, and every subagent's tokens. The session model rolls them up; you don't have to think about which CC session was which.

What does *not* count: hook sessions that ran before the DWB session was opened (no link), and hook sessions on other projects (those roll up under those projects' DWB sessions).

**Why two layers (regex + AI)?**

The regex layer is instant - it fires synchronously when you submit a message - and it catches the predictable open/close phrases without spending TL tokens evaluating them. The AI layer is the backstop for the long tail: phrases the regex doesn't know about, ambiguous wording, and clarifications. The dashboard shows which layer caught each open/close so the regex catalogue can grow over time.

**What if the regex catches the open but I didn't actually mean to open?**

Rare but possible. You can close the session immediately - a regex-opened session closes the same way as any other.

**Can a session span multiple days?**

Yes - if there's activity. The idle sweeper only closes sessions that have been quiet for the idle threshold (60 minutes default). A long-running session with periodic activity stays open as long as you want.

**Where do I see active and recent sessions?**

The dashboard panel (planned in DWB-339) shows the current session for the project plus a recent-sessions list. Until that lands, the API endpoints are: `GET /api/projects/{id}/sessions` for the list and `GET /api/sessions/{id}` for the detail view with the role/ticket/overhead breakdowns.
