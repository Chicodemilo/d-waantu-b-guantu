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
# Data Out: extract_keywords (pure TF), rank_tfidf (TF-IDF, DWB-500),
#           normalize_term, tokenize, is_ticket_key, KeywordWeight, STOPWORDS,
#           TICKET_KEY_RE
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
# TWO RANKERS (DWB-500):
#   - extract_keywords: pure TF. `weight` = raw per-session occurrence COUNT.
#   - rank_tfidf: TF-IDF. `weight` = an int RELEVANCE SCORE (tf * idf), NOT a
#     count. Terms common across many sessions sink; session-distinctive terms
#     rise. IDF = log((N+1)/(df+1)) (no outside +1 floor, so a term in EVERY
#     session -> 0 -> dropped). df/N come from the stored keyword distribution,
#     passed IN by the DB-aware caller (dwb_session_rollup.compute_session_
#     document_frequencies) - this module stays pure/DB-free. The close path
#     (dwb_session._assemble_rollup) uses rank_tfidf, so what lands in
#     entity_keywords.weight is the relevance score. Below 2 documents IDF is
#     degenerate, so rank_tfidf falls back to pure-TF (extract_keywords).

from __future__ import annotations

import math
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
        # DWB-499: number-words (cardinals + ordinals) - "one" was ranking 133 in
        # live session tags. Pure counting noise, never session-distinctive.
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
        "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
        "thousand", "million", "billion",
        "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
        "eighth", "ninth", "tenth",
        # DWB-499: obvious generic English filler spotted scanning real session
        # corpora (47/36). Deliberately NOT DWB domain terms (ticket/session/
        # keyword/summary/sprint stay OUT - their cross-session ubiquity is
        # TF-IDF's job, not the stopword list's).
        "real", "really", "new", "actually", "basically", "thing", "things",
        "lot", "lots", "stuff", "etc", "via", "per", "also", "able", "okay",
        "ok", "yeah", "yep", "nope",
        # DWB-500: filler surfaced once TF-IDF lifted it out of the TF shadow.
        "already",
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
    - Returns None when nothing usable remains (e.g. pure punctuation), OR when
      the term has no letters (DWB-500: bare numbers like "1"/"2"/"100" and
      digit-only fragments are counting noise, the digit analogue of the
      number-words dropped in DWB-499; ticket keys are exempt - handled above).
    """
    stripped = _EDGE_PUNCT_RE.sub("", raw)
    if not stripped:
        return None
    if is_ticket_key(stripped):
        return stripped.upper()
    lowered = stripped.lower()
    kebab = _INNER_SEP_RE.sub("-", lowered).strip("-")
    if not kebab:
        return None
    # Drop tokens with no alphabetic character (bare digits / numeric fragments).
    if not any(ch.isalpha() for ch in kebab):
        return None
    return kebab


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
    counts = _tally(texts)

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


def rank_tfidf(
    texts: Iterable[str],
    *,
    document_frequencies: dict[str, int],
    total_documents: int,
    min_frequency: int = DEFAULT_MIN_FREQUENCY,
    top_n: int = DEFAULT_TOP_N,
) -> list[KeywordWeight]:
    """Rank a corpus's terms by TF-IDF relevance (DWB-500).

    Same TF pass as extract_keywords, then each term's raw TF is multiplied by an
    inverse-document-frequency factor so terms common across MANY sessions sink
    and session-distinctive terms rise. Unlike extract_keywords, the returned
    `KeywordWeight.weight` is a TF-IDF RELEVANCE SCORE (int), not a raw count -
    so a consumer that sorts by weight desc (the synthesizer + the read API)
    reflects relevance directly.

    IDF = log((N + 1) / (df + 1))   [N = total documents, df = docs containing
    the term]. The +1s guard div-by-zero and smooth; there is deliberately NO
    outside +1 floor (that would keep IDF >= 1 and let a high-TF ubiquitous term
    keep dominating). A term in EVERY document -> df = N -> IDF = 0 -> dropped
    (pure boilerplate is not distinctive). `document_frequencies` is sourced from
    the stored keyword distribution; a term absent from it has df = 0 (treated as
    maximally distinctive).

    Selection / scoring:
      - score = tf * idf (float, used for ranking).
      - Non-ticket terms must clear `min_frequency` (TF) AND have score > 0.
      - Ticket keys (DWB-468) are ALWAYS kept verbatim regardless of TF/score,
        and emitted in addition to the top_n normal terms (same contract as
        extract_keywords).
      - Stored weight = max(1, round(score)) so a kept tag is never 0 (488).
      - Ranked by score desc, then keyword asc (deterministic).

    Bootstrap guard: TF-IDF needs at least 2 documents to mean anything. With
    `total_documents` < 2 (a fresh/empty corpus, e.g. the first close or an
    isolated test transaction) IDF is degenerate (every term -> 0), so this
    falls back to pure-TF ranking via extract_keywords - identical to today's
    behaviour until a real cross-session distribution exists.
    """
    if total_documents < 2:
        return extract_keywords(texts, min_frequency=min_frequency, top_n=top_n)

    counts = _tally(texts)
    n = total_documents

    # Build (KeywordWeight, score_float) pairs; rank by the precise float score.
    keys: list[tuple[KeywordWeight, float]] = []
    normals: list[tuple[KeywordWeight, float]] = []
    for term, tf in counts.items():
        df = document_frequencies.get(term, 0)
        score = tf * math.log((n + 1) / (df + 1))
        kw = KeywordWeight(term, max(1, round(score)), is_ticket_key(term))
        if kw.is_ticket_key:
            # Always kept verbatim; floored to >=1 even if df makes idf ~0.
            keys.append((kw, score))
        elif tf >= min_frequency and score > 0:
            normals.append((kw, score))

    rank = lambda pair: (-pair[1], pair[0].keyword)  # noqa: E731 - stable key
    keys.sort(key=rank)
    normals.sort(key=rank)
    normals = normals[: max(top_n, 0)]

    merged = keys + normals
    merged.sort(key=rank)
    return [kw for kw, _score in merged]


def _tally(texts: Iterable[str]) -> Counter:
    """Tokenise + normalise the corpus and count non-stopword term frequencies.
    Shared by extract_keywords (pure TF) and rank_tfidf (TF-IDF)."""
    counts: Counter[str] = Counter()
    for text in texts:
        for token in tokenize(text):
            if token in STOPWORDS:
                continue
            counts[token] += 1
    return counts
