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

You open a session by saying something the TL recognizes as an open phrase. The detection runs in two main layers (plus the `/dwb-open` slash escape hatch, shown in the method table below). A former Layer-2 async Haiku classifier was retired in DWB-402; its `ai_classifier` method survives only as a legacy value on historical rows.

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
| `regex` | Regex fast-path caught it on a hook (instant) |
| `ai_classifier` | Retired (DWB-402): legacy value on historical rows; no new opens use it |
| `slash` | `/dwb-open` slash command (deterministic escape hatch) |
| `ai_confident` | TL reasoning - acted without asking |
| `ai_asked` | TL reasoning - confirmed with you first |

**The caller never supplies the open timestamp.** `opened_at` is server-stamped (`now()`); on the AI methods (`ai_confident`/`ai_asked`) any value sent is ignored, because a hand-built timestamp can be hours wrong. Omit the field.

For regex-method opens, the matched catalogue phrase is recorded on the row (it comes from the hardcoded list in `session_phrases.py`, not free-form user text). For AI-layer opens, only the `open_method` enum is kept; the user's literal message is never persisted.

**A phrase occurrence can open exactly one session, ever (DWB-682).** The Layer 1 scan reads the transcript, and the transcript still contains this morning's open phrase at line one. Before this landed, every close was followed by a scan, the scan found that phrase again, and a new session opened: close it, and it came straight back.

The fix is a consumed position rather than a clock. Each session records `open_transcript_key`, the identity of the single transcript entry whose phrase opened it, taken from the `uuid` Claude Code stamps on every entry. The scan refuses to open a second session from an entry whose key is already present **for that project** (two projects can resolve from one working directory, and an entry spent for one has not been spent for the other).

Worth knowing why it is not a timestamp floor: comparing a transcript entry's wall clock against a DB-stamped `opened_at` is a cross-clock comparison, and MySQL rounds a fractional datetime half-up into a second-precision column, so a Python stamp carrying microseconds can land in the future of a row written after it. A consumed position is deterministic and reads no clock.

## Closing a session

Same model as open, in reverse. You signal you want to stop, and the system closes the session.

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

**Idle auto-close.** If you forget to close, the system catches it. A background sweeper runs every 5 minutes (`IDLE_SWEEP_INTERVAL_SECONDS`, default 300), and any open session whose last activity is older than the idle threshold auto-closes. **That threshold is `IDLE_TIMEOUT_MINUTES`, which defaults to 600 minutes, i.e. 10 hours, not 1.** An unattended session therefore survives a long gap before the sweeper takes it. The session is tagged `close_method=idle_timeout`, `close_reason=idle` so the dashboard can distinguish a forgotten close from an explicit one.

**Required headline (TL closes).** `ai_confident`/`ai_asked` closes MUST carry a `headline` - 5 to 10 words describing what the session did (it becomes the dashboard SUMMARY). The close is **rejected 422** without one, and the rejection carries the session window (`opened_at` to now) so the TL can summarise the right span. Machine-driven closes (`regex`/`slash`/`idle_timeout`/`ai_classifier`) are exempt - they have no summariser.

**Write-on-close gate (TL closes).** An `ai_confident`/`ai_asked` close is **rejected 422** if the TL has no memory write inside this session's window. The refusal names the TL, gives the window start, and tells you where to write. It is explicit that this is a rule and not a delay: write, then close.

The route it names depends on the project's memory mode, and that is the half that was wrong until DWB-688. On a **stock** project it names `POST /api/agents/{agent_id}/memory/append` (or `/session-complete`). On a **`human_memory`** project those are sealed at 409, so it names `POST /api/agents/{agent_id}/memories` and states that all four of `body`, `condensed`, `keywords`, `situation` are REQUIRED. Before that fix the gate told a human_memory TL to call a sealed route, which made it unpassable by following its own instructions.

Only the wording was ever wrong. The check itself reads the right store in both modes and always has, so a single `POST /api/agents/{agent_id}/memories` row satisfies it on human_memory.

**Compaction gate (TL closes).** Before an `ai_confident`/`ai_asked` close can complete, every spawn-loaded doc must be within its token ceiling. The close is **rejected 422** until then, listing each over-ceiling file and its owner. Owners compact in parallel, autonomously: on a **stock** project each agent rewrites its own memory files leaner and submits via `POST /api/agents/{id}/memory/compact {file, content}` (a full-file replace; the server rejects it if the result is still over ceiling, so a no-op can't satisfy the gate). On a **`human_memory`** project `memory/compact` is sealed at 409 (DWB-589) and agent memory has no token ceiling at all, so there is nothing for an agent to compact and nothing of theirs that can hold this gate open: it is a TL-only check there, over the shared root docs. The TL compacts the shared root docs (HANDOFF / ARCHITECTURE / README). Machine-driven closes are exempt.

### Verifying the open set: COUNT ROWS, never infer

Do not write "all sessions closed" into a handoff on the strength of having closed one. **Closing a session does not mean the open set is empty, and it never did.** An IND team lead wrote exactly that while session 3680 was still open, and only found out because a worker's journal carried a session id he did not recognise.

Two separate reasons a close can leave something open:

- **The grace-window resurrect un-closes the same row, deliberately (DWB-395).** `reopen_session` nulls `closed_at`, `close_method`, `close_reason` and `close_phrase` on the row you just closed, and `is_open` is a generated column that recomputes from `closed_at`, so the row goes straight back to open. Nothing is created, so a check that looks for a *new* session sees nothing wrong.
- **Another project may have its own open session.** The single-active rule is per project, not global (see "Multi-project").

**The supported way to count:**

```
GET /api/projects/{project_id}/sessions     # valid params: limit, offset
```

Every row carries `status`, which is `open` or `closed`. Count the rows whose `status` is `open`. That is the check, and it is a count rather than a judgement.

Two shapes that look like an answer and are not, both of which DWB-530 made say so out loud rather than mislead you:

- `GET /api/projects/{project_id}/sessions?status=open` is **refused with 400**, naming `status` as an unknown param and listing `limit, offset`. It does not silently return the unfiltered list, which would read as "these are the open ones".
- `GET /api/sessions?project_id=X&status=open` has **no collection form** and is refused with 400 naming the two routes that do exist. It used to fall through to a bare 404, and a 404 there reads as "no open session" when it actually means "no such route".

### How the close is recorded

| `close_method` | Meaning |
|---|---|
| `regex` | Regex phrase match on a hook |
| `ai_classifier` | Retired (DWB-402): legacy value on historical rows; no new closes use it |
| `slash` | `/dwb-close` slash command |
| `ai_confident` | TL reasoning - acted without asking |
| `ai_asked` | TL reasoning - confirmed with you first |
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
- **Ad Hoc** - worker session tokens for small fixes the user waived the ticket workflow on (see the skip-ceremony rule in the TL playbook). These tokens route to the bucket automatically instead of firing an unattributed alert.

**Computed aggregates.** The dashboard's Recent Sessions strip also shows `tickets_made`, `tickets_completed`, `agents_active`, `open_method`, `close_method`, and the `headline` (or auto-derived `ticket_summary`) per session. These are derived automatically from existing tracking data - no extra signaling from the user or workers is needed.

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

Nothing breaks. The idle sweeper closes it for you after the idle threshold, which defaults to **600 minutes (10 hours)**, not 60. Expect it to sit open for the rest of the day rather than clearing itself within the hour. The session is marked `close_method=idle_timeout`, `close_reason=idle` so the dashboard can show it was an auto-close rather than an explicit one.

If you want to close it manually later, hit `POST /api/sessions/{id}/close` with `close_method=ai_confident` and `close_reason=manual` to record an operator close cleanly.

**How do I check nothing is still open before I write the handoff?**

Count rows, do not infer it from having closed one. `GET /api/projects/{project_id}/sessions` and count the rows whose `status` is `open`. Do not reach for `?status=open`; it is refused as an unknown param. See "Verifying the open set" above for why a close can leave a row open and why the two obvious shortcuts mislead.

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

Yes - if there's activity. The idle sweeper only closes sessions that have been quiet for the idle threshold (`IDLE_TIMEOUT_MINUTES`, default 600 minutes). A long-running session with periodic activity stays open as long as you want.

**Where do I see active and recent sessions?**

The dashboard panel on the project page shows the current session plus a recent-sessions list (DWB-339, shipped). The API endpoints behind it are `GET /api/projects/{project_id}/sessions` for the list (valid params: `limit`, `offset`) and `GET /api/sessions/{session_id}` for the detail view with the role/ticket/overhead breakdowns.
