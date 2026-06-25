# Path: app/services/keyword_extraction.py
# File: keyword_extraction.py
# Created: 2026-06-25
# Purpose: Pure, deterministic keyword extraction + normalization for session
#          write-ups (DWB-482). Turns a corpus of activity text (ticket
#          titles/descriptions, commit messages, comms, comments, agent/role
#          names) into ranked weighted keywords. NO LLM, NO network, NO DB - it
#          operates only on the strings the caller passes in, so the same input
#          always yields the same output. The DWB-483 synthesizer gathers the
#          corpus and persists EntityKeyword rows (DWB-481) from the result.
# Caller: app/services/* (session synthesizer, DWB-483)
# Callees: re, collections, dataclasses (stdlib only)
# Data In: an iterable of plain-text strings (the activity corpus)
# Data Out: extract_keywords, normalize_term, tokenize, is_ticket_key,
#           KeywordWeight, STOPWORDS, TICKET_KEY_RE
# Last Modified: 2026-06-25
#
# HARD PRIVACY RULE (DWB-351): this module must NEVER be fed user-typed prompt
# text. The corpus is agent-produced activity ONLY - ticket titles and
# descriptions, commit messages that reference the session's ticket keys, comms
# summaries/bodies, comments, and agent/role names. The function is pure and
# cannot police its inputs, so the contract lives with the caller: do not pass
# raw user prompts. (DWB persists no user prompt text anyway; this keeps the
# corpus on the safe side of that line.)
#
# FUTURE (documented, NOT built - TF-IDF down-weighting): today `weight` is the
# raw per-session term frequency (TF). A term that is common across EVERY
# session (e.g. "ticket", "sprint", a recurring agent name) scores high in every
# write-up even though it carries little signal about THIS session. A later
# enhancement would multiply TF by an inverse-document-frequency factor computed
# across all sessions (IDF = log(total_sessions / sessions_containing_term)), so
# session-distinctive terms rank above boilerplate. That needs a corpus-wide
# document-frequency table and is deliberately out of scope here; the substrate
# (entity_keywords.weight as an int count + entity_type/entity_id) already
# supports recomputing weights later without a schema change.

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

# Ticket keys (DWB-468): PREFIX-NUMBER, e.g. DWB-468, CI-401, RVP-007. Kept
# verbatim (canonicalised to upper-case) regardless of frequency and never
# tokenised into pieces or stopword-filtered. Prefix is 2+ letters so a stray
# "a-1" or a hyphenated word does not masquerade as a key.
TICKET_KEY_RE = re.compile(r"^[A-Za-z]{2,}-\d+$")

# A token is a run of letters/digits, optionally with internal hyphens or
# underscores (so "system-ops" and "Archie_DWB" survive as one token rather
# than splitting into fragments). Surrounding punctuation is stripped before
# this is applied.
_TOKEN_SPLIT_RE = re.compile(r"\s+")
_EDGE_PUNCT_RE = re.compile(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$")
_INNER_SEP_RE = re.compile(r"[^0-9a-z]+")

# Default ranking knobs. min_frequency is the floor a NORMAL term must clear to
# be kept (ticket keys bypass it); top_n caps how many frequency-ranked normal
# terms are emitted (ticket keys are emitted in addition, never cut by the cap).
DEFAULT_MIN_FREQUENCY = 2
DEFAULT_TOP_N = 50

# Standard English stopwords. Dropped after normalisation, so "The" x60 and
# "the" x60 both fall out, while a non-stopword like "tmux" x50 is kept and
# ranks high. Kept intentionally generic (no domain terms) so DWB vocabulary
# ("ticket", "sprint", "agent") still surfaces - cross-session boilerplate is
# the TF-IDF enhancement's job (see header), not the stopword list's.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "about", "above", "after", "again", "against", "all", "am", "an",
        "and", "any", "are", "aren", "as", "at", "be", "because", "been",
        "before", "being", "below", "between", "both", "but", "by", "can",
        "cannot", "could", "couldn", "did", "didn", "do", "does", "doesn",
        "doing", "don", "down", "during", "each", "few", "for", "from",
        "further", "had", "hadn", "has", "hasn", "have", "haven", "having",
        "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
        "i", "if", "in", "into", "is", "isn", "it", "its", "itself", "just",
        "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of",
        "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves",
        "out", "over", "own", "re", "s", "same", "she", "should", "shouldn",
        "so", "some", "such", "t", "than", "that", "the", "their", "theirs",
        "them", "themselves", "then", "there", "these", "they", "this",
        "those", "through", "to", "too", "under", "until", "up", "very", "was",
        "wasn", "we", "were", "weren", "what", "when", "where", "which",
        "while", "who", "whom", "why", "will", "with", "won", "would",
        "wouldn", "you", "your", "yours", "yourself", "yourselves",
    }
)


@dataclass(frozen=True)
class KeywordWeight:
    """One ranked keyword and its per-session occurrence count.

    `keyword` is the normalised term (ticket keys verbatim/upper-cased, all
    other terms lower-cased and kebab-cased). `weight` is the raw frequency
    across the corpus. `is_ticket_key` flags terms matched by TICKET_KEY_RE,
    which are kept regardless of the min-frequency floor. Maps directly onto an
    EntityKeyword row (DWB-481): keyword -> keyword, weight -> weight.
    """

    keyword: str
    weight: int
    is_ticket_key: bool


def is_ticket_key(token: str) -> bool:
    """True when `token` is a ticket key (PREFIX-NUMBER, DWB-468)."""
    return bool(TICKET_KEY_RE.match(token))


def normalize_term(raw: str) -> str | None:
    """Normalise a single raw token to its canonical keyword form.

    - Strips surrounding punctuation.
    - Ticket keys (DWB-468) are preserved verbatim, upper-cased so case variants
      ("dwb-468", "DWB-468") dedupe to one term.
    - Everything else is lower-cased and kebab-cased: any run of inner
      separators (underscores, slashes, dots, stray punctuation) collapses to a
      single hyphen, so "Archie_DWB" -> "archie-dwb", "team/lead" -> "team-lead",
      and an already-kebab "system-ops" is unchanged.
    - Returns None when nothing usable remains (e.g. pure punctuation).
    """
    stripped = _EDGE_PUNCT_RE.sub("", raw)
    if not stripped:
        return None
    if is_ticket_key(stripped):
        return stripped.upper()
    lowered = stripped.lower()
    kebab = _INNER_SEP_RE.sub("-", lowered).strip("-")
    return kebab or None


def tokenize(text: str) -> list[str]:
    """Split free text into normalised keyword tokens (order preserved).

    Whitespace-delimited so compound identifiers stay intact for normalisation;
    each piece runs through normalize_term. Empty/punctuation-only pieces drop
    out. Ticket keys come back verbatim (upper-cased).
    """
    if not text:
        return []
    out: list[str] = []
    for piece in _TOKEN_SPLIT_RE.split(text):
        if not piece:
            continue
        term = normalize_term(piece)
        if term:
            out.append(term)
    return out


def extract_keywords(
    texts: Iterable[str],
    *,
    min_frequency: int = DEFAULT_MIN_FREQUENCY,
    top_n: int = DEFAULT_TOP_N,
) -> list[KeywordWeight]:
    """Extract ranked, weighted keywords from a corpus of activity text.

    Deterministic: same input -> same output (stable secondary sort by term).

    Pipeline:
      1. Tokenise + normalise every string (lower/kebab; ticket keys verbatim).
      2. Drop English stopwords (ticket keys are never stopwords).
      3. Count frequencies across the whole corpus (the weight).
      4. Ticket keys are kept regardless of frequency (bypass the floor).
      5. Normal terms must clear `min_frequency`.
      6. Rank by weight desc, then term asc for a stable tie-break.
      7. Cap the NORMAL terms at `top_n`; ticket keys are emitted in addition
         and are never cut by the cap.

    Args:
        texts: the activity corpus (NO user-typed prompt text - see header).
        min_frequency: floor a normal term must reach to be kept (keys exempt).
        top_n: max number of frequency-ranked normal terms to emit.

    Returns:
        A list of KeywordWeight, ranked. Ticket keys and normal terms are
        merged into one ranked list (keys always present).
    """
    counts: Counter[str] = Counter()
    for text in texts:
        for token in tokenize(text):
            if token in STOPWORDS:
                continue
            counts[token] += 1

    keys: list[KeywordWeight] = []
    normals: list[KeywordWeight] = []
    for term, weight in counts.items():
        if is_ticket_key(term):
            keys.append(KeywordWeight(term, weight, True))
        elif weight >= min_frequency:
            normals.append(KeywordWeight(term, weight, False))

    rank = lambda kw: (-kw.weight, kw.keyword)  # noqa: E731 - tiny stable key
    keys.sort(key=rank)
    normals.sort(key=rank)
    normals = normals[: max(top_n, 0)]

    merged = keys + normals
    merged.sort(key=rank)
    return merged
