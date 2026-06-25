// Path: src/hooks/useFuzzyFilter.js
// File: useFuzzyFilter.js
// Created: 2026-06-25
// Purpose: Lightweight, dependency-free fuzzy matcher (DWB-468). Exposes a pure
//          scorer (fuzzyScore), a pure list filter (fuzzyFilter) returning ranked
//          matches plus the set of matched ids so a parent can force-open them, and
//          a memoised React hook (default export) wrapping fuzzyFilter. Generic and
//          presentational-friendly: takes a list of { id, text } and a query string.
// Caller: components/help/FuzzySearch.jsx, pages/HelpPage.jsx, and any consumer that
//         needs live substring/subsequence filtering without an npm dependency.
// Callees: react (useMemo)
// Data In: items = [{ id, text }], query string
// Data Out: { results: matchedItems[], matchedIds: Set } (default hook + fuzzyFilter);
//           fuzzyScore returns a number (higher = better) or null (no match)
// Last Modified: 2026-06-25

import { useMemo } from 'react';

// Score a single text against a query.
// Returns a number where higher = stronger match, or null when there is no match.
// A direct substring match always outranks a looser subsequence match.
export function fuzzyScore(text, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return 0;
  const t = (text || '').toLowerCase();
  if (!t) return null;

  // Strongest: contiguous substring. Earlier position ranks higher.
  const idx = t.indexOf(q);
  if (idx !== -1) {
    return 1000 - idx;
  }

  // Weaker: all query chars appear in order (subsequence). Tighter span ranks higher.
  let ti = 0;
  let qi = 0;
  let firstHit = -1;
  let lastHit = -1;
  while (ti < t.length && qi < q.length) {
    if (t[ti] === q[qi]) {
      if (firstHit === -1) firstHit = ti;
      lastHit = ti;
      qi += 1;
    }
    ti += 1;
  }
  if (qi === q.length) {
    const span = lastHit - firstHit + 1;
    // Reject loose subsequence hits: chars scattered across a long string are
    // noise, not a match. Allow some slack for gaps/typos, scaled to query length.
    const maxSpan = q.length * 5 + 8;
    if (span > maxSpan) return null;
    // Base 500 keeps subsequence hits below any substring hit (min 1000 - len).
    return 500 - span;
  }

  return null;
}

// Filter + rank a list of { id, text } items against a query.
// Blank query => every item passes (no filtering) and matchedIds is empty,
// so a parent does NOT force any section open until the user actually types.
export function fuzzyFilter(items, query) {
  const list = Array.isArray(items) ? items : [];
  const q = (query || '').trim();
  if (!q) {
    return { results: list, matchedIds: new Set() };
  }

  const scored = [];
  for (const item of list) {
    const score = fuzzyScore(item && item.text, q);
    if (score !== null && score !== undefined) {
      scored.push({ item, score });
    }
  }
  scored.sort((a, b) => b.score - a.score);

  return {
    results: scored.map((s) => s.item),
    matchedIds: new Set(scored.map((s) => s.item.id)),
  };
}

// Memoised hook form for use inside components.
export default function useFuzzyFilter(items, query) {
  return useMemo(() => fuzzyFilter(items, query), [items, query]);
}
