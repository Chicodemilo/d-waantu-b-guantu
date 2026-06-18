# Path: app/config/session_phrases.py
# File: session_phrases.py
# Created: 2026-06-09
# Purpose: Versioned regex patterns + matchers for DWB session open/close detection (DWB-336)
# Caller: app/services/dwb_sessions.py, app/services/hook_tracking.py
# Callees: re (stdlib)
# Data In: free-form user text
# Data Out: matched phrase substring or None
# Last Modified: 2026-06-17
#
# DWB-378 (2026-06-11): broadened _CLOSE_SOURCES with target-suffixed +
# lighter wrap-up variants observed missing from real CI sessions (idle_timeout
# was the only close path firing for those evenings).
# DWB-394 (2026-06-17): close-matcher negative-context guard. match_close now
# (a) compiles the <name> slot on CLOSE patterns with a stop-word exclusion so
# reported-speech fillers ("shut down last/when/it/that") can't satisfy it, and
# (b) skips any matched span that sits in interrogative / reported-speech
# context (sentence contains "?", or a marker like "when i said"/"didn't"/"why"
# precedes the span). Open-side matching is unchanged.

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
    # DWB-378: target-suffixed + lighter wrap-up variants. The <name>
    # placeholder uses the same alphanumeric-token compile as the open
    # side, so "shut down ci" and "wrap up barry for the night" both
    # match. Bare "time" or "logging" alone won't trip these because
    # the trailing-clause discriminator is required.
    "shut down for the night",
    "shut down <name>",
    "shut down <name> for the night",
    "wrap up <name>",
    "wrap up <name> for the night",
    "done for the day",
    "done for the night",
    "logging off",
    "lets close it",
    "time to close",
    "thats it for tonight",
    "thats it for the night",
]


# ---- Compilation ----


_NAME_PLACEHOLDER = "DWBNAMETOKEN"  # alphanumeric: survives re.escape unchanged
_WHITESPACE_PLACEHOLDER = "DWBWSTOKEN"  # alphanumeric: survives re.escape unchanged
_WHITESPACE_RE = re.compile(r"\s+")

# DWB-394: stop words that must NOT satisfy the close-pattern ``<name>`` slot.
# Without this, "shut down <name>" compiled ``<name>`` to a bare ``\w+`` and
# "shut down last", "shut down when", "shut down it", "shut down that" all
# matched the name slot — so a question like "...when I said shut down last?"
# tripped a false close. These are the function words / interrogatives that
# show up in reported speech and questions about shutting down, never as a
# real agent name. Real agent names (archie, barry, pam, ci, dwb, ...) are not
# in this set, so genuine "shut down archie" / "wrap up barry" still match.
_CLOSE_NAME_STOPWORDS: list[str] = [
    "last", "when", "it", "that", "this", "the", "a", "an",
    "for", "and", "now", "then", "today", "tonight", "if",
    "what", "why", "how", "did", "didnt", "should", "is", "was",
    "to", "of", "i", "we", "you", "they", "yet", "again", "ever",
]

# The close-side ``<name>`` slot: any alphanumeric token EXCEPT a stop word.
# The negative lookahead is anchored at the name position (zero-width) so a
# match still returns the full "shut down archie" span. Stop words are matched
# whole-token via the trailing ``\b`` so "shutdown" / longer names that merely
# start with a stop word ("forrest") are unaffected.
_CLOSE_NAME_PATTERN = (
    r"(?!(?:" + "|".join(_CLOSE_NAME_STOPWORDS) + r")\b)\w+"
)

# DWB-394: reported-speech / interrogative markers. When one of these precedes
# the matched close span within the same sentence (or the sentence contains a
# "?"), the close phrase is being quoted or questioned, not commanded, and
# match_close must NOT fire. Covers the catalogue called out in the ticket:
# "when i said", "said", "say", "why", "what", "how", "didn't", "should",
# "if i", "what does", "what happens".
_NEG_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"when\s+i\s+said|"
    r"what\s+does|what\s+happens|"
    r"if\s+i|"
    r"said|saying|say|"
    r"why|what|how|"
    r"didn['’]?t|did\s+not|"
    r"should"
    r")\b",
    re.IGNORECASE,
)

# Sentence-boundary characters used to scope the negative-context check to the
# clause that actually contains the matched span.
_SENT_BOUNDARY = ".!?\n"


def _compile(source: str, *, name_pattern: str = r"\w+") -> re.Pattern[str]:
    """Compile a source string into a fuzzy-whitespace, case-insensitive regex.

    Strategy — substitute placeholders BEFORE escaping, restore AFTER:

      1. Swap every ``<name>`` for the alphanumeric placeholder
         ``DWBNAMETOKEN``. Alphanumerics pass through ``re.escape`` unchanged.
      2. Swap each whitespace run for the alphanumeric placeholder
         ``DWBWSTOKEN``. Same reason — preserves the fuzzy-whitespace slot
         across the escape pass without also escaping the slot character.
      3. ``re.escape`` the whole result so phrase punctuation (commas,
         apostrophes, hyphens) becomes literal regex matches.
      4. Restore: placeholders → ``name_pattern`` and ``\\s+`` respectively.

    Result for ``"you are <name>, read the playbook"`` is the regex
    ``"you\\s+are\\s+\\w+,?\\s+read\\s+the\\s+playbook"`` (compiled
    case-insensitive), which matches the real user phrase plus all the
    whitespace and case variants. The escape step preserves the literal
    comma (re.escape leaves commas alone), and a final pass (DWB-376)
    relaxes any ``,\\s+`` to ``,?\\s+`` so the comma is optional in
    natural English ("you are archie read your playbook" matches the
    same as "you are archie, read your playbook"). The whitespace run
    is still required; only the comma itself is relaxed.

    ``name_pattern`` (DWB-394): the regex fragment the ``<name>`` placeholder
    expands to. Open patterns keep the permissive ``\\w+`` (the trailing
    clause is the discriminator). Close patterns pass the stop-word-excluding
    ``_CLOSE_NAME_PATTERN`` so reported-speech fillers ("shut down last",
    "shut down when", "shut down that") no longer satisfy the name slot. The
    fragment is inserted AFTER ``re.escape`` so its own regex metacharacters
    (lookahead, alternation, ``\\b``) survive intact.

    Why not split-on-whitespace tokens: a token like ``<name>,`` doesn't
    equal ``<name>`` and the original implementation escaped it as a
    literal, breaking every comma-bearing pattern. The placeholder
    approach avoids that class of bug entirely.
    """
    s = source.replace("<name>", _NAME_PLACEHOLDER)
    s = _WHITESPACE_RE.sub(_WHITESPACE_PLACEHOLDER, s)
    s = re.escape(s)
    s = s.replace(_NAME_PLACEHOLDER, name_pattern)
    s = s.replace(_WHITESPACE_PLACEHOLDER, r"\s+")
    # DWB-376: make the comma between <name> and the trailing clause
    # optional so natural-English "you are archie read your playbook"
    # matches the same as the comma form. The whitespace run is still
    # required; only the comma itself is relaxed. Applies to OPEN and
    # CLOSE sources alike (CLOSE has no commas today but the rule must
    # not regress them if any are added later).
    s = s.replace(r",\s+", r",?\s+")
    return re.compile(s, re.IGNORECASE)


OPEN_PATTERNS: list[re.Pattern[str]] = [_compile(s) for s in _OPEN_SOURCES]
# DWB-394: close patterns use the stop-word-excluding name slot so reported-
# speech fillers can't satisfy "<name>". Open patterns keep the permissive
# default (criterion: leave open-side matching unchanged).
CLOSE_PATTERNS: list[re.Pattern[str]] = [
    _compile(s, name_pattern=_CLOSE_NAME_PATTERN) for s in _CLOSE_SOURCES
]


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


def _close_match_is_negated(text: str, start: int, end: int) -> bool:
    """DWB-394: True when the close span at ``[start, end)`` sits in
    interrogative / reported-speech context and so must NOT close a session.

    Two guards, both scoped to the sentence that contains the span (sentence
    boundaries: ``. ! ? \\n``):

      1. The sentence contains a ``?`` — the whole clause is a question
         ("...didn't close when I said shut down last?"), not a command.
      2. A reported-speech / interrogative marker (``_NEG_CONTEXT_RE``)
         appears in the sentence text BEFORE the span ("when I said shut
         down archie", "why did you shut it down").

    Scoping to the current sentence avoids false negatives where a prior
    sentence was a question but the close command stands on its own
    ("Are you done? shut it down for the night.").
    """
    # Sentence start: just after the previous boundary char (or 0).
    sent_start = 0
    for i in range(start - 1, -1, -1):
        if text[i] in _SENT_BOUNDARY:
            sent_start = i + 1
            break
    # Sentence end: include the trailing boundary char so a closing "?" is
    # part of the sentence we inspect.
    sent_end = len(text)
    for i in range(end, len(text)):
        if text[i] in _SENT_BOUNDARY:
            sent_end = i + 1
            break

    sentence = text[sent_start:sent_end]
    if "?" in sentence:
        return True

    preceding = text[sent_start:start]
    if _NEG_CONTEXT_RE.search(preceding):
        return True

    return False


def match_close(text: str | None) -> str | None:
    """Return the first matching close-phrase substring, or None.

    Same semantics as ``match_open``: the slice of ``text`` that matched,
    stored in ``dwb_sessions.close_phrase`` on close.

    DWB-394: a matched span is skipped when it sits in interrogative /
    reported-speech context (see ``_close_match_is_negated``). We iterate
    every occurrence of every pattern and return the first NON-negated span,
    so a real command later in the text still closes even if an earlier
    quoted/questioned span matched first ("I didn't say shut down last;
    anyway, shut it down for the night").
    """
    if not text:
        return None
    for pat in CLOSE_PATTERNS:
        for m in pat.finditer(text):
            if _close_match_is_negated(text, m.start(), m.end()):
                continue
            return m.group(0)
    return None
