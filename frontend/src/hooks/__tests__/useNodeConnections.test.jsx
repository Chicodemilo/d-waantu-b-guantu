// Path: src/hooks/__tests__/useNodeConnections.test.jsx
// File: useNodeConnections.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the connections fan-out hook (DWB-543): nothing is fetched while disabled, with zero matches, or above the 25-match cap; when enabled with a small match set it calls GET /nodes/match once per distinct matched tag and returns the union of neighbor ids minus the matches themselves; a change in matches aborts the in-flight fan-out and a stale result is discarded; a single failed call surfaces as error while the rest still merge; an identical match list rebuilt on re-render does not refetch.
// Caller: vitest test runner
// Callees: ../useNodeConnections, ../../api/nodes (mocked)
// Data In: Mocked matchProjectNodes responses in the live NodeMatchResponse shape
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup, waitFor } from '@testing-library/react';

vi.mock('../../api/nodes', () => ({
  getProjectNodes: vi.fn(),
  matchProjectNodes: vi.fn(),
}));

import useNodeConnections, { MAX_CONNECTION_MATCHES, connectionsEligible } from '../useNodeConnections';
import { matchProjectNodes } from '../../api/nodes';

const N = (id, tag) => ({ id, tag, weight: 10, pointers: [] });
const NB = (id) => ({ id, tag: `n${id}`, weight: 5, shared_refs: ['x'] });
const resp = (node, neighbors) => ({ query: node.tag, query_tags: [node.tag], nodes: [{ ...node, neighbors }] });

describe('useNodeConnections (DWB-543)', () => {
  beforeEach(() => {
    matchProjectNodes.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('eligibility is 1..MAX matches', () => {
    expect(connectionsEligible(0)).toBe(false);
    expect(connectionsEligible(1)).toBe(true);
    expect(connectionsEligible(MAX_CONNECTION_MATCHES)).toBe(true);
    expect(connectionsEligible(MAX_CONNECTION_MATCHES + 1)).toBe(false);
  });

  it('fetches nothing while disabled, with no matches, or above the cap', async () => {
    const one = [N(1, 'a')];
    const many = Array.from({ length: MAX_CONNECTION_MATCHES + 1 }, (_, i) => N(i + 1, `t${i}`));
    const { result, rerender } = renderHook(({ m, on }) => useNodeConnections('1', m, on), { initialProps: { m: one, on: false } });
    expect(result.current.connectedIds.size).toBe(0);
    expect(result.current.eligible).toBe(true);
    rerender({ m: [], on: true });
    expect(result.current.eligible).toBe(false);
    rerender({ m: many, on: true });
    expect(result.current.eligible).toBe(false);
    await act(async () => {});
    expect(matchProjectNodes).not.toHaveBeenCalled();
    expect(result.current.connectedIds.size).toBe(0);
    expect(result.current.loading).toBe(false);
  });

  it('enabled with a small set: one call per distinct tag, neighbors merged, matches excluded', async () => {
    const matches = [N(1, 'alpha'), N(2, 'beta'), N(3, 'beta')];
    matchProjectNodes.mockImplementation((pid, text) => {
      if (text === 'alpha') return Promise.resolve(resp(matches[0], [NB(10), NB(11), { ...NB(2), tag: 'beta' }]));
      if (text === 'beta') return Promise.resolve(resp(matches[1], [NB(11), NB(12), { ...NB(1), tag: 'alpha' }]));
      return Promise.resolve({ query: text, query_tags: [], nodes: [] });
    });
    const { result } = renderHook(() => useNodeConnections('1', matches, true));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(matchProjectNodes).toHaveBeenCalledTimes(2);
    expect(matchProjectNodes.mock.calls.map((c) => c[1]).sort()).toEqual(['alpha', 'beta']);
    expect(matchProjectNodes.mock.calls[0][2]).toEqual(expect.objectContaining({ signal: expect.anything() }));
    expect([...result.current.connectedIds].sort((a, b) => a - b)).toEqual([10, 11, 12]);
    expect(result.current.error).toBeNull();
  });

  it('aborts the fan-out when matches change and discards the stale result', async () => {
    let resolveA;
    matchProjectNodes.mockImplementation((pid, text) => {
      if (text === 'a') return new Promise((r) => { resolveA = r; });
      return Promise.resolve(resp(N(2, 'b'), [NB(20)]));
    });
    const first = [N(1, 'a')];
    const second = [N(2, 'b')];
    const { result, rerender } = renderHook(({ m }) => useNodeConnections('1', m, true), { initialProps: { m: first } });
    await act(async () => {});
    const firstSignal = matchProjectNodes.mock.calls[0][2].signal;
    rerender({ m: second });
    expect(firstSignal.aborted).toBe(true);
    await waitFor(() => expect([...result.current.connectedIds]).toEqual([20]));
    await act(async () => { resolveA(resp(N(1, 'a'), [NB(99)])); });
    expect([...result.current.connectedIds]).toEqual([20]);
  });

  it('a failed call surfaces as error while the other results still merge', async () => {
    matchProjectNodes.mockImplementation((pid, text) => (
      text === 'bad' ? Promise.reject(new Error('down')) : Promise.resolve(resp(N(1, 'ok'), [NB(7)]))
    ));
    const { result } = renderHook(() => useNodeConnections('1', [N(1, 'ok'), N(2, 'bad')], true));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect([...result.current.connectedIds]).toEqual([7]);
    expect(result.current.error?.message).toBe('down');
  });

  it('turning the toggle off clears the set without a request', async () => {
    matchProjectNodes.mockResolvedValue(resp(N(1, 'a'), [NB(5)]));
    const { result, rerender } = renderHook(({ on }) => useNodeConnections('1', [N(1, 'a')], on), { initialProps: { on: true } });
    await waitFor(() => expect([...result.current.connectedIds]).toEqual([5]));
    rerender({ on: false });
    expect(result.current.connectedIds.size).toBe(0);
    expect(matchProjectNodes).toHaveBeenCalledTimes(1);
  });

  it('an identical match list with a new array identity does not refetch', async () => {
    matchProjectNodes.mockResolvedValue(resp(N(1, 'a'), [NB(5)]));
    const { result, rerender } = renderHook(({ m }) => useNodeConnections('1', m, true), { initialProps: { m: [N(1, 'a')] } });
    await waitFor(() => expect([...result.current.connectedIds]).toEqual([5]));
    rerender({ m: [N(1, 'a')] });
    rerender({ m: [N(1, 'a')] });
    await act(async () => {});
    expect(matchProjectNodes).toHaveBeenCalledTimes(1);
    // a different id set does refetch
    rerender({ m: [N(2, 'b')] });
    await waitFor(() => expect(matchProjectNodes).toHaveBeenCalledTimes(2));
  });
});
