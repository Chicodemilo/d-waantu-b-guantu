# Path: app/services/dwb_session_search.py
# File: dwb_session_search.py
# Created: 2026-06-25
# Purpose: Cross-session FULLTEXT search + ranking over dwb_sessions.search_text (DWBG-011). Ranks by MATCH relevance, boosted by summed entity_keywords.weight for matched terms, recency tiebreaker; supports project/agent/epic/date facets.
# Caller: app/routers/dwb_sessions.py
# Callees: app.models.entity_keyword (keyword boost); raw SQL over dwb_sessions / hook_sessions / tickets
# Data In: SQLAlchemy Session + query string + optional facets
# Data Out: list[dict] ranked search hits (one per matching session)
# Last Modified: 2026-06-25

"""Cross-session search service (DWBG-011).

The search substrate is the STORED generated column dwb_sessions.search_text
(DWBG-010) and its FULLTEXT index. This module turns a query + facets into a
ranked list of sessions:

  1. FULLTEXT match: `MATCH(search_text) AGAINST(:q IN NATURAL LANGUAGE MODE)`
     filters to relevant rows and yields the primary relevance score.
  2. Keyword boost: the per-session sum of entity_keywords.weight for keywords
     whose term appears in the query. Sessions whose mined keywords (ticket
     keys, distinctive terms) line up with the query rank higher than ones that
     merely share prose. Computed in ONE batched query over the candidate ids -
     no N+1.
  3. Recency tiebreaker: opened_at DESC breaks ties so a fresher session wins
     when relevance + boost are equal.

Facets (all optional, ANDed):
  - project_id: scope to one project. Omitted = cross-project search.
  - agent_id:   only sessions a given agent worked (a linked hook_session).
  - epic_id:    only sessions where a ticket on that epic completed in the
                session window.
  - from / to:  date range on opened_at.

Privacy: search_text is built only from agent-produced prose (headline +
synthesized summary + TL narrative); no user prompt text is ever indexed
(DWB-351 / DWBG-003), so search cannot surface user-typed content.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.entity_keyword import EntityKeyword

# Each unit of summed keyword weight is worth this much added to the raw
# FULLTEXT relevance when ranking. Tuned so a strong keyword alignment can lift
# a row over a marginally-more-relevant one, without letting a high-weight
# keyword set bury a clearly-more-relevant prose match. Exposed in the response
# (score = relevance + factor * keyword_boost) so ordering is explainable.
KEYWORD_BOOST_FACTOR = 0.5

# Snippet window (characters) taken around the first matched term in search_text.
_SNIPPET_RADIUS = 60

# Tokenize a query into terms for the keyword-boost match. Keeps ticket-key
# shapes (DWBG-011) and bare words; drops punctuation and FULLTEXT boolean
# operators (+ - * " < > ( )) so a boolean-styled query still boosts on its
# bare terms. Lowercased for case-insensitive keyword comparison.
_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def tokenize_query(q: str) -> list[str]:
    """Split a raw query into lowercased bare terms for keyword matching.

    Deduplicated, order preserved. Drops boolean-mode operators and stray
    punctuation so `"+recall -stale"` boosts on `recall` and `stale`.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _TERM_RE.findall(q.lower()):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _keyword_boost_by_session(
    db: Session, session_ids: list[int], terms: list[str]
) -> dict[int, float]:
    """Sum entity_keywords.weight per session for keywords matching any query
    term (case-insensitive exact match on the kebab/keyword token). ONE batched
    query over the candidate session ids - no N+1. Sessions with no matching
    keyword are absent from the returned map (treated as 0 boost by the caller).
    """
    if not session_ids or not terms:
        return {}
    rows = db.execute(
        select(
            EntityKeyword.entity_id,
            func.coalesce(func.sum(EntityKeyword.weight), 0).label("boost"),
        )
        .where(EntityKeyword.entity_type == "dwb_session")
        .where(EntityKeyword.entity_id.in_(session_ids))
        # Keywords are stored kebab/verbatim; match case-insensitively against
        # the lowercased query terms.
        .where(func.lower(EntityKeyword.keyword).in_(terms))
        .group_by(EntityKeyword.entity_id)
    ).all()
    return {r.entity_id: float(r.boost) for r in rows}


def _snippet(search_text: str | None, terms: list[str]) -> str | None:
    """Return a short slice of search_text around the first matched term, or
    None when there is nothing to show. Used for the result card preview."""
    if not search_text:
        return None
    lowered = search_text.lower()
    pos = -1
    for t in terms:
        i = lowered.find(t)
        if i != -1 and (pos == -1 or i < pos):
            pos = i
    if pos == -1:
        # No inline term hit (e.g. NL-mode matched a stem); fall back to the head.
        return search_text[: _SNIPPET_RADIUS * 2].strip() or None
    start = max(0, pos - _SNIPPET_RADIUS)
    end = min(len(search_text), pos + _SNIPPET_RADIUS)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(search_text) else ""
    return f"{prefix}{search_text[start:end].strip()}{suffix}"


def search_sessions(
    db: Session,
    *,
    q: str,
    project_id: int | None = None,
    agent_id: int | None = None,
    epic_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Run a ranked cross-session search. Returns a list of result dicts sorted
    by combined score (FULLTEXT relevance + keyword boost) then recency.

    The caller (router) owns query validation (empty/blank q is rejected before
    this is called) and shaping the dicts into the response schema.

    Two queries total: (1) the FULLTEXT-filtered + faceted candidate fetch with
    its relevance score, ordered + paginated in SQL; (2) the batched keyword
    boost over the returned page's ids. Keyword chips are NOT fetched here - the
    router reuses the DWB-493 batched keyword read so the chip shape stays one
    place.
    """
    # MATCH ... AGAINST in natural-language mode is both the filter (only rows
    # the FULLTEXT index matched) and the relevance score. SQLAlchemy's generic
    # column operators do not emit the required `AGAINST (...)` parens, so the
    # whole statement is composed as a parameterized raw SQL string. The MATCH
    # expression appears in SELECT (aliased `relevance`) and WHERE (filter), so
    # InnoDB uses the FULLTEXT index for the filter; both reference the single
    # named bindparam `:q_match`. Facets are appended as additional AND clauses
    # with their own named binds. All values are bound (never interpolated), so
    # the query is injection-safe despite being a string.
    match_expr = (
        "MATCH(dwb_sessions.search_text) "
        "AGAINST (:q_match IN NATURAL LANGUAGE MODE)"
    )

    where_clauses = [match_expr]
    params: dict = {"q_match": q, "limit": limit, "offset": offset}

    if project_id is not None:
        where_clauses.append("dwb_sessions.project_id = :project_id")
        params["project_id"] = project_id
    if date_from is not None:
        where_clauses.append("dwb_sessions.opened_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        where_clauses.append("dwb_sessions.opened_at <= :date_to")
        params["date_to"] = date_to

    # agent_id facet: the session must have a linked hook_session for that agent.
    if agent_id is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM hook_sessions hs "
            "WHERE hs.dwb_session_id = dwb_sessions.id "
            "AND hs.agent_id = :agent_id)"
        )
        params["agent_id"] = agent_id

    # epic_id facet: a ticket on that epic completed within the session window
    # [opened_at, closed_at] (open sessions clamp the upper bound at "now" via
    # COALESCE(closed_at, now())). Mirrors the rollup window convention.
    if epic_id is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM tickets t "
            "WHERE t.epic_id = :epic_id "
            "AND t.project_id = dwb_sessions.project_id "
            "AND t.completed_at IS NOT NULL "
            "AND t.completed_at >= dwb_sessions.opened_at "
            "AND t.completed_at <= COALESCE(dwb_sessions.closed_at, NOW()))"
        )
        params["epic_id"] = epic_id

    # Order by relevance desc, recency desc as tiebreaker. The keyword boost is
    # folded in after the fetch (it can only raise a row that already matched the
    # FULLTEXT filter, and re-sorting a bounded page in Python is cheap and keeps
    # the boost SQL out of the hot relevance query). The page is taken on the
    # relevance+recency order - the dominant ranking signal - then the boost
    # reorders within that page.
    sql = (
        "SELECT dwb_sessions.id, dwb_sessions.project_id, dwb_sessions.headline, "
        "dwb_sessions.opened_at, dwb_sessions.closed_at, "
        "dwb_sessions.total_tokens, dwb_sessions.search_text, "
        f"{match_expr} AS relevance "
        "FROM dwb_sessions "
        f"WHERE {' AND '.join(where_clauses)} "
        "ORDER BY relevance DESC, dwb_sessions.opened_at DESC "
        "LIMIT :limit OFFSET :offset"
    )

    rows = db.execute(text(sql), params).all()
    if not rows:
        return []

    ids = [r.id for r in rows]
    terms = tokenize_query(q)
    boost_map = _keyword_boost_by_session(db, ids, terms)

    results: list[dict] = []
    for r in rows:
        boost = boost_map.get(r.id, 0.0)
        relevance_val = float(r.relevance or 0.0)
        results.append(
            {
                "id": r.id,
                "project_id": r.project_id,
                "headline": r.headline,
                "opened_at": r.opened_at,
                "closed_at": r.closed_at,
                "total_tokens": int(r.total_tokens or 0),
                "relevance": relevance_val,
                "keyword_boost": boost,
                "score": relevance_val + KEYWORD_BOOST_FACTOR * boost,
                "snippet": _snippet(r.search_text, terms),
            }
        )

    # Final ordering by combined score, recency as tiebreaker (negate epoch for
    # a stable desc on the secondary key).
    results.sort(key=lambda d: (d["score"], d["opened_at"]), reverse=True)
    return results
