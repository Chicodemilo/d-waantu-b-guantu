# Path: app/services/session_synthesizer.py
# File: session_synthesizer.py
# Created: 2026-06-25
# Purpose: Deterministic session-summary synthesizer (DWB-483). ONE pure pass over a
#          pre-assembled session rollup -> three outputs: headline, structured summary
#          JSON, normalized weighted keywords. NO DB, NO LLM, NO network, NO user prompt
#          text (privacy, DWB-351). Pure given a rollup fixture -> trivially unit-testable.
# Caller: app/services/dwb_session.py (close_session wiring, DWB-484)
# Callees: none (stdlib only)
# Data In: rollup: dict (see ROLLUP CONTRACT in the module docstring)
# Data Out: dict {"headline": str|None, "summary": dict, "keywords": list[dict]}
# Last Modified: 2026-06-25

"""Deterministic session-summary synthesizer (DWB-483).

``synthesize_session_summary(rollup)`` is a PURE function: same rollup in, same
outputs out. It touches no database, makes no network call, runs no model, and
never echoes user-typed prompt text. The caller (DWB-484, ``close_session``)
assembles the rollup from the read-only helpers in ``dwb_session_rollup.py`` plus
the DWB-482 keyword extractor, then persists the three outputs.

ROLLUP CONTRACT (input dict; every field optional, synthesizer degrades gracefully):

    {
      # closer-supplied headline (ai_confident / ai_asked). Passed through verbatim
      # when present; otherwise the synthesizer fabricates one.
      "headline": str | None,

      # dwb_session_rollup.compute_by_role()
      "by_role": [{"agent_id", "agent_name", "role", "tokens", "time_seconds"}],

      # dwb_session_rollup.compute_by_ticket() - tickets WORKED in the window
      "by_ticket": [{"ticket_id", "ticket_key", "title", "tokens", "time_seconds"}],

      # dwb_session_rollup.compute_list_aggregates()
      "tickets_made": int,
      "tickets_completed": int,
      "agents_active": int,
      "ticket_summary": str | None,     # "Epic Name (N)" dominant-epic string

      # optional richer list of completed-in-window tickets for named bullets
      "completed_tickets": [{"ticket_key", "title"}],

      # frozen totals from close_session
      "total_tokens": int,
      "total_time_seconds": int,

      # DWB-482 extractor output: (keyword, weight) pairs OR {"keyword","weight"} dicts
      "keywords": [(str, int), ...] | [{"keyword": str, "weight": int}, ...],
    }

OUTPUT:

    {
      "headline": str | None,          # supplied passthrough, else synthesized; None only when no activity
      "summary": {                     # the LOCKED contract consumed by DWB-486
        "lead": str,
        "sections": [{"title": str, "bullets": [str]}],
      },
      "keywords": [{"keyword": str, "weight": int}],   # sorted weight desc, keyword asc; capped
    }
"""

import re

# Max words in a synthesized headline (DWB-346: 5 to 10 words).
_HEADLINE_MAX_WORDS = 10
# Max named tickets listed inline in a summary bullet before "(+k more)".
_TICKET_LIST_CAP = 5
# Max keyword tags emitted.
_KEYWORD_CAP = 20

_EPIC_COUNT_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def _plural(n: int, word: str) -> str:
    """'1 ticket' / '2 tickets' - deterministic, no locale."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _fmt_duration(seconds: int) -> str:
    """Whole-number 'Hh Mm' (or 'Mm' under an hour). Negative clamps to 0."""
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _epic_name(ticket_summary: str | None) -> str | None:
    """Strip the trailing ' (N)' count from a 'Epic Name (N)' string."""
    if not ticket_summary:
        return None
    name = _EPIC_COUNT_SUFFIX.sub("", ticket_summary).strip()
    return name or None


def _trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _has_activity(rollup: dict) -> bool:
    return bool(
        rollup.get("tickets_made")
        or rollup.get("tickets_completed")
        or rollup.get("agents_active")
        or rollup.get("by_ticket")
        or rollup.get("total_tokens")
    )


def _synthesize_headline(rollup: dict) -> str | None:
    """Fabricate a 5-10 word 'what the session did' headline (DWB-346) when the
    closer supplied none. Deterministic. None only when there is no activity."""
    if not _has_activity(rollup):
        return None

    completed = int(rollup.get("tickets_completed") or 0)
    made = int(rollup.get("tickets_made") or 0)
    agents = int(rollup.get("agents_active") or 0)
    by_ticket = rollup.get("by_ticket") or []
    epic = _epic_name(rollup.get("ticket_summary"))

    if completed > 0:
        head = f"Completed {_plural(completed, 'ticket')}"
        if epic:
            head += f" in {epic}"
        else:
            keys = [t.get("ticket_key") for t in by_ticket[:2] if t.get("ticket_key")]
            if keys:
                head += ": " + ", ".join(keys)
    elif made > 0:
        head = f"Created {_plural(made, 'ticket')}"
        if agents > 0:
            head += f" across {_plural(agents, 'agent')}"
    elif by_ticket:
        keys = [t.get("ticket_key") for t in by_ticket[:2] if t.get("ticket_key")]
        worked = ", ".join(keys) if keys else _plural(len(by_ticket), "ticket")
        head = f"Worked {worked}"
        if agents > 0:
            head += f" with {_plural(agents, 'agent')}"
    else:
        # Tokens/agents only, no ticket churn.
        head = f"Session activity across {_plural(max(agents, 1), 'agent')}"

    return _trim_words(head, _HEADLINE_MAX_WORDS)


def _named_ticket_bullet(prefix: str, tickets: list[dict]) -> str:
    """'prefix: KEY title; KEY title (+k more)' from a list of ticket dicts."""
    shown = tickets[:_TICKET_LIST_CAP]
    parts = []
    for t in shown:
        key = (t.get("ticket_key") or "").strip()
        title = (t.get("title") or "").strip()
        label = f"{key} {title}".strip() or key or "(untitled)"
        parts.append(label)
    extra = len(tickets) - len(shown)
    body = "; ".join(parts)
    if extra > 0:
        body += f" (+{extra} more)"
    return f"{prefix}: {body}"


def _build_summary(rollup: dict, headline: str | None) -> dict:
    """Build the locked summary JSON: {lead, sections:[{title, bullets}]}.
    Sections are emitted only when they carry content, in a fixed order."""
    sections: list[dict] = []

    # --- Tickets ---
    ticket_bullets: list[str] = []
    completed = int(rollup.get("tickets_completed") or 0)
    made = int(rollup.get("tickets_made") or 0)
    completed_tickets = [
        t for t in (rollup.get("completed_tickets") or []) if t.get("ticket_key")
    ]
    if completed > 0:
        if completed_tickets:
            ticket_bullets.append(
                _named_ticket_bullet(f"{completed} completed", completed_tickets)
            )
        elif rollup.get("ticket_summary"):
            ticket_bullets.append(f"{completed} completed (mostly {rollup['ticket_summary']})")
        else:
            ticket_bullets.append(f"{completed} completed")
    if made > 0:
        ticket_bullets.append(f"{made} created")
    by_ticket = rollup.get("by_ticket") or []
    if by_ticket:
        ticket_bullets.append(
            _named_ticket_bullet(f"Worked {_plural(len(by_ticket), 'ticket')}", by_ticket)
        )
    if ticket_bullets:
        sections.append({"title": "Tickets", "bullets": ticket_bullets})

    # --- Team ---
    team_bullets: list[str] = []
    agents = int(rollup.get("agents_active") or 0)
    if agents > 0:
        team_bullets.append(f"{_plural(agents, 'agent')} active")
    role_tokens: dict[str, int] = {}
    for r in rollup.get("by_role") or []:
        role = r.get("role") or "unknown"
        role_tokens[role] = role_tokens.get(role, 0) + int(r.get("tokens") or 0)
    for role, tok in sorted(role_tokens.items(), key=lambda kv: (-kv[1], kv[0])):
        if tok > 0:
            team_bullets.append(f"{role}: {tok:,} tokens")
    if team_bullets:
        sections.append({"title": "Team", "bullets": team_bullets})

    # --- Cost ---
    total_tokens = int(rollup.get("total_tokens") or 0)
    total_time = int(rollup.get("total_time_seconds") or 0)
    if total_tokens > 0 or total_time > 0:
        sections.append({
            "title": "Cost",
            "bullets": [f"{total_tokens:,} tokens over {_fmt_duration(total_time)}"],
        })

    lead = headline or "No tracked activity this session."
    return {"lead": lead, "sections": sections}


def _normalize_keywords(raw) -> list[dict]:
    """Normalize the DWB-482 extractor output (tuples or dicts) into
    [{"keyword": str, "weight": int}] sorted by weight desc, keyword asc, capped.
    Empty/blank keywords are dropped; non-int weights coerce to 0."""
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, dict):
            keyword = item.get("keyword")
            weight = item.get("weight")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            keyword, weight = item[0], item[1]
        else:
            continue
        if keyword is None:
            continue
        keyword = str(keyword).strip()
        if not keyword:
            continue
        try:
            weight = int(weight)
        except (TypeError, ValueError):
            weight = 0
        out.append({"keyword": keyword, "weight": weight})
    out.sort(key=lambda d: (-d["weight"], d["keyword"]))
    return out[:_KEYWORD_CAP]


def synthesize_session_summary(rollup: dict | None) -> dict:
    """Pure synthesizer entry point (DWB-483). See module docstring for the
    rollup contract and output shape. Deterministic; no side effects."""
    rollup = rollup or {}
    supplied = (rollup.get("headline") or "").strip()
    headline = supplied or _synthesize_headline(rollup)
    summary = _build_summary(rollup, headline)
    keywords = _normalize_keywords(rollup.get("keywords"))
    return {"headline": headline, "summary": summary, "keywords": keywords}
