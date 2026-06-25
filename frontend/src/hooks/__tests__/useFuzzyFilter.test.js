// Path: src/hooks/__tests__/useFuzzyFilter.test.js
// File: useFuzzyFilter.test.js
// Created: 2026-06-25
// Purpose: Unit tests for the dependency-free fuzzy matcher (DWB-468): fuzzyScore
//          ranking (substring beats subsequence, no-match returns null) and
//          fuzzyFilter (blank query passthrough with empty matchedIds, ranked
//          results, matchedIds set for force-open, case-insensitivity).
// Caller: vitest test runner
// Callees: ../useFuzzyFilter (fuzzyScore, fuzzyFilter)
// Data In: synthetic item lists + queries
// Data Out: test assertions
// Last Modified: 2026-06-25

import { describe, it, expect } from 'vitest';
import { fuzzyScore, fuzzyFilter } from '../useFuzzyFilter';

describe('fuzzyScore (DWB-468)', () => {
  it('returns 0 for an empty query (everything matches)', () => {
    expect(fuzzyScore('tickets', '')).toBe(0);
    expect(fuzzyScore('tickets', '   ')).toBe(0);
  });

  it('returns null when there is no match', () => {
    expect(fuzzyScore('tickets', 'zzz')).toBeNull();
    expect(fuzzyScore('', 'abc')).toBeNull();
  });

  it('matches a contiguous substring and is case-insensitive', () => {
    expect(fuzzyScore('Inter-Agent Comms', 'comms')).not.toBeNull();
    expect(fuzzyScore('Inter-Agent Comms', 'COMMS')).not.toBeNull();
  });

  it('ranks an earlier substring position higher', () => {
    const early = fuzzyScore('agent comms', 'agent');
    const late = fuzzyScore('inter agent', 'agent');
    expect(early).toBeGreaterThan(late);
  });

  it('matches a non-contiguous subsequence', () => {
    // a..g..t appears in order inside "activity grid testing"
    expect(fuzzyScore('activity grid testing', 'agt')).not.toBeNull();
  });

  it('ranks a substring match above a subsequence match', () => {
    const sub = fuzzyScore('test run', 'test'); // substring
    const seq = fuzzyScore('t-e-x-s-t', 'test'); // subsequence only
    expect(sub).toBeGreaterThan(seq);
  });

  it('does not match when chars are out of order', () => {
    expect(fuzzyScore('abc', 'cba')).toBeNull();
  });
});

describe('fuzzyFilter (DWB-468)', () => {
  const items = [
    { id: 'tickets', text: 'tickets board' },
    { id: 'team', text: 'team roster' },
    { id: 'sessions', text: 'sessions and tokens' },
    { id: 'comms', text: 'inter-agent comms' },
  ];

  it('passes everything through and matches nothing on a blank query', () => {
    const { results, matchedIds } = fuzzyFilter(items, '');
    expect(results).toHaveLength(4);
    expect(matchedIds.size).toBe(0);
  });

  it('filters to matching items and exposes their ids', () => {
    const { results, matchedIds } = fuzzyFilter(items, 'comms');
    expect(results.map((r) => r.id)).toEqual(['comms']);
    expect(matchedIds.has('comms')).toBe(true);
    expect(matchedIds.has('tickets')).toBe(false);
  });

  it('returns ranked results (best score first)', () => {
    const list = [
      { id: 'a', text: 'a wild team appears' },
      { id: 'b', text: 'team roster' },
    ];
    const { results } = fuzzyFilter(list, 'team');
    // "team roster" starts with the query -> ranks above the mid-string match
    expect(results[0].id).toBe('b');
  });

  it('trims whitespace-only queries to a passthrough', () => {
    const { results, matchedIds } = fuzzyFilter(items, '   ');
    expect(results).toHaveLength(4);
    expect(matchedIds.size).toBe(0);
  });

  it('handles a non-array input safely', () => {
    const { results, matchedIds } = fuzzyFilter(null, 'x');
    expect(results).toEqual([]);
    expect(matchedIds.size).toBe(0);
  });
});
