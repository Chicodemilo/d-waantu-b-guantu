// Path: src/hooks/__tests__/useNodeMatch.test.jsx
// File: useNodeMatch.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the debounced node match hook (DWB-536): no request for an empty query (matchIds null = not limiting), a single request after the debounce window even when several keystrokes land inside it, the matched id set + normalized query_tags bound from the live response shape, an empty query restoring the idle state, and a stale response being discarded when a newer query supersedes it.
// Caller: vitest test runner
// Callees: ../useNodeMatch, ../../api/nodes (mocked)
// Data In: Mocked matchProjectNodes responses; fake timers
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

vi.mock('../../api/nodes', () => ({
  getProjectNodes: vi.fn(),
  matchProjectNodes: vi.fn(),
}));

import useNodeMatch, { NODE_MATCH_DEBOUNCE_MS } from '../useNodeMatch';
import { matchProjectNodes } from '../../api/nodes';

const response = (text, tags, ids) => ({ query: text, query_tags: tags, nodes: ids.map((id) => ({ id, tag: `t${id}`, weight: 10, pointers: [], neighbors: [] })) });

describe('useNodeMatch (DWB-536)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    matchProjectNodes.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('does not request for an empty or whitespace query and reports not-limiting', () => {
    const { result, rerender } = renderHook(({ q }) => useNodeMatch('1', q), { initialProps: { q: '' } });
    expect(result.current.matchIds).toBeNull();
    expect(result.current.loading).toBe(false);
    rerender({ q: '   ' });
    act(() => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS * 2); });
    expect(matchProjectNodes).not.toHaveBeenCalled();
    expect(result.current.matchIds).toBeNull();
  });

  it('debounces: several keystrokes inside the window produce exactly one request for the final text', async () => {
    matchProjectNodes.mockImplementation((pid, text) => Promise.resolve(response(text, [text], [517])));
    const { result, rerender } = renderHook(({ q }) => useNodeMatch('1', q), { initialProps: { q: 'c' } });
    expect(result.current.loading).toBe(true);
    act(() => { vi.advanceTimersByTime(100); });
    rerender({ q: 'con' });
    act(() => { vi.advanceTimersByTime(100); });
    rerender({ q: 'contract' });
    act(() => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS - 1); });
    expect(matchProjectNodes).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(matchProjectNodes).toHaveBeenCalledTimes(1);
    expect(matchProjectNodes).toHaveBeenCalledWith('1', 'contract', expect.objectContaining({ signal: expect.anything() }));
    expect(result.current.matchIds).toEqual(new Set([517]));
    expect(result.current.queryTags).toEqual(['contract']);
    expect(result.current.settledQuery).toBe('contract');
    expect(result.current.loading).toBe(false);
  });

  it('binds the live shape: zero-node responses yield an empty set and the normalized tags', async () => {
    matchProjectNodes.mockResolvedValue(response('sprint close gate', ['gate', 'sprint'], []));
    const { result } = renderHook(() => useNodeMatch('1', 'sprint close gate'));
    await act(async () => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS); });
    expect(result.current.matchIds).toEqual(new Set());
    expect(result.current.queryTags).toEqual(['gate', 'sprint']);
  });

  it('clearing the query restores the idle state immediately', async () => {
    matchProjectNodes.mockResolvedValue(response('roster', ['roster'], [1631]));
    const { result, rerender } = renderHook(({ q }) => useNodeMatch('1', q), { initialProps: { q: 'roster' } });
    await act(async () => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS); });
    expect(result.current.matchIds).toEqual(new Set([1631]));
    rerender({ q: '' });
    expect(result.current.matchIds).toBeNull();
    expect(result.current.queryTags).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it('discards a stale response when a newer query has superseded it', async () => {
    let resolveFirst;
    matchProjectNodes.mockImplementation((pid, text) => {
      if (text === 'a') return new Promise((r) => { resolveFirst = r; });
      return Promise.resolve(response(text, [text], [2]));
    });
    const { result, rerender } = renderHook(({ q }) => useNodeMatch('1', q), { initialProps: { q: 'a' } });
    await act(async () => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS); });
    expect(matchProjectNodes).toHaveBeenCalledTimes(1);
    rerender({ q: 'b' });
    await act(async () => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS); });
    expect(result.current.matchIds).toEqual(new Set([2]));
    // late first response arrives after abort: ignored
    await act(async () => { resolveFirst(response('a', ['a'], [1])); });
    expect(result.current.matchIds).toEqual(new Set([2]));
    expect(result.current.settledQuery).toBe('b');
  });

  it('surfaces a failed match as an empty limiter plus error', async () => {
    matchProjectNodes.mockImplementation(() => Promise.reject(new Error('down')));
    const { result } = renderHook(() => useNodeMatch('1', 'x'));
    await act(async () => { vi.advanceTimersByTime(NODE_MATCH_DEBOUNCE_MS); });
    expect(result.current.error?.message).toBe('down');
    expect(result.current.matchIds).toEqual(new Set());
  });
});
