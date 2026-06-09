# Path: app/config/session_phrases.py
# File: session_phrases.py
# Created: 2026-06-09
# Purpose: Versioned regex patterns + matchers for DWB session open/close detection (DWB-336)
# Caller: app/services/dwb_sessions.py, app/services/hook_tracking.py
# Callees: re (stdlib)
# Data In: free-form user text
# Data Out: matched phrase substring or None
# Last Modified: 2026-06-09

"""Versioned regex catalogue for the DWB session-lifecycle regex fast path.

Layer 1 of DWB session detection (DWB-336): a small library of compiled
regexes that match the human-user's open/close phrases. When a match fires,
the caller posts to /api/sessions/open or /api/sessions/{id}/close with
``open_method="regex"`` / ``close_method="regex"``. Layer 2 (TL AI reasoning)
covers everything the regex misses.

Adding a new phrase is intentionally a one-line job: extend ``_OPEN_SOURCES``
or ``_CLOSE_SOURCES``. The compiled lists ``OPEN_PATTERNS`` /
``CLOSE_PATTERNS`` re-derive at module load. Two helper functions,
``match_open(text)`` and ``match_close(text)``, return the matched substring
on hit (suitable for storing in ``open_phrase`` / ``close_phrase``) or
``None`` on miss.

Design notes:

- All patterns are matched **case-insensitive** and with **fuzzy whitespace**
  (\\s+ between tokens). The source strings here use a single space; the
  compiler swaps each run of whitespace for ``\\s+`` automatically.
- The ``<name>`` token in open patterns is a placeholder for the agent name
  the user is addressing ("you are archie, ..."). It compiles to ``\\w+`` so
  any single alphanumeric token matches — the discriminator is the trailing
  half of the phrase ("read the playbook"), not the name. A bare "you are
  archie" alone deliberately won't match; chitchat shouldn't open sessions.
- Patterns are searched with ``re.search`` (not ``fullmatch``) so they fire
  on the relevant clause even when wrapped in other text.
"""

import re

# ---- Source phrases (human-readable, fuzzy-whitespace-aware) ----
#
# Each source string is a token sequence. Tokens are separated by single
# spaces; the compiler maps every run of spaces to ``\\s+`` so the matcher
# tolerates newlines, double-spaces, tabs, etc.
#
# Special tokens:
#   <name>      ->  \\w+  (single alphanumeric token, the agent name)
#
# Add new variants by appending to these lists. Order doesn't matter for
# matching, but keeping the most-common variants at the top makes the
# search slightly faster on the hot path.

_OPEN_SOURCES: list[str] = [
    # Today's actual open phrase (HANDOFF.md note, 2026-06-08):
    "you are <name>, you are team lead, read the playbook",
    "you are <name>, you are team lead, read your playbook",
    # Single-clause "read the playbook" variants
    "you are <name>, read the playbook",
    "you are <name>, read your playbook",
    "you are <name>, read your handoff and playbook",
    "you are <name>, read the handoff and playbook",
    # Without leading "you are <name>"
    "read your handoff and playbook",
    "read the handoff and playbook",
    "read your playbook and handoff",
    # Explicit DWB session open
    "open a dwb session",
    "open the dwb session",
    "open a session",
    "open the session",
    # Just "read your handoff" (less common but observed)
    "you are <name>, read your handoff",
]

_CLOSE_SOURCES: list[str] = [
    "have the team write docs and exit",
    "team write docs and exit",
    "write docs and exit",
    "close the session",
    "close this session",
    "close the dwb session",
    "shut it down for the night",
    "shut it down",
    "wrap it up for the night",
    "wrap up for the night",
    "end of session",
    "that's a wrap",
]


# ---- Compilation ----


_NAME_PLACEHOLDER = "DWBNAMETOKEN"  # alphanumeric: survives re.escape unchanged
_WHITESPACE_PLACEHOLDER = "DWBWSTOKEN"  # alphanumeric: survives re.escape unchanged
_WHITESPACE_RE = re.compile(r"\s+")


def _compile(source: str) -> re.Pattern[str]:
    """Compile a source string into a fuzzy-whitespace, case-insensitive regex.

    Strategy — substitute placeholders BEFORE escaping, restore AFTER:

      1. Swap every ``<name>`` for the alphanumeric placeholder
         ``DWBNAMETOKEN``. Alphanumerics pass through ``re.escape`` unchanged.
      2. Swap each whitespace run for the alphanumeric placeholder
         ``DWBWSTOKEN``. Same reason — preserves the fuzzy-whitespace slot
         across the escape pass without also escaping the slot character.
      3. ``re.escape`` the whole result so phrase punctuation (commas,
         apostrophes, hyphens) becomes literal regex matches.
      4. Restore: placeholders → ``\\w+`` and ``\\s+`` respectively.

    Result for ``"you are <name>, read the playbook"`` is the regex
    ``"you\\s+are\\s+\\w+,\\s+read\\s+the\\s+playbook"`` (compiled
    case-insensitive), which matches the real user phrase plus all the
    whitespace and case variants. The escape step preserves the literal
    comma — re.escape leaves commas alone.

    Why not split-on-whitespace tokens: a token like ``<name>,`` doesn't
    equal ``<name>`` and the original implementation escaped it as a
    literal, breaking every comma-bearing pattern. The placeholder
    approach avoids that class of bug entirely.
    """
    s = source.replace("<name>", _NAME_PLACEHOLDER)
    s = _WHITESPACE_RE.sub(_WHITESPACE_PLACEHOLDER, s)
    s = re.escape(s)
    s = s.replace(_NAME_PLACEHOLDER, r"\w+")
    s = s.replace(_WHITESPACE_PLACEHOLDER, r"\s+")
    return re.compile(s, re.IGNORECASE)


OPEN_PATTERNS: list[re.Pattern[str]] = [_compile(s) for s in _OPEN_SOURCES]
CLOSE_PATTERNS: list[re.Pattern[str]] = [_compile(s) for s in _CLOSE_SOURCES]


# ---- Matchers ----


def match_open(text: str | None) -> str | None:
    """Return the first matching open-phrase substring, or None.

    The returned substring is the exact slice of ``text`` that matched —
    suitable for storing in ``dwb_sessions.open_phrase`` so the dashboard
    can show what triggered the open.
    """
    if not text:
        return None
    for pat in OPEN_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def match_close(text: str | None) -> str | None:
    """Return the first matching close-phrase substring, or None.

    Same semantics as ``match_open``: the slice of ``text`` that matched,
    stored in ``dwb_sessions.close_phrase`` on close.
    """
    if not text:
        return None
    for pat in CLOSE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None
