// Path: src/hooks/__tests__/useNodeify.test.jsx
// File: useNodeify.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the rescan hook (DWB-551): idle shape, running flag across a pass, the report on success with the onDone refetch callback, the error captured on failure without throwing, and the re-entry guard that stops a second concurrent pass (the backend 500s on one) while still allowing a later pass.
// Caller: vitest test runner
// Callees: ../useNodeify, ../../api/nodes (mocked)
// Data In: Mocked nodeifyProject responses in the live NodeifyResponse shape
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup, waitFor } from '@testing-library/react';

vi.mock('../../api/nodes', () => ({
  getProjectNodes: vi.fn(),
  matchProjectNodes: vi.fn(),
  nodeifyProject: vi.fn(),
}));

import useNodeify from '../useNodeify';
import { nodeifyProject } from '../../api/nodes';

const REPORT = {
  project_id: 1,
  nodeified_at: '2026-09-15T19:10:00',
  source_counts: { code: 900, doc: 40, memory: 8 },
  grounded: 3420,
  pruned: 12,
  suppressed: 271,
  pointers_written: 68916,
};

describe('useNodeify (DWB-551)', () => {
  beforeEach(() => {
    nodeifyProject.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('starts idle and does nothing without a project id', async () => {
    const { result } = renderHook(() => useNodeify(null));
    expect(result.current.running).toBe(false);
    expect(result.current.report).toBeNull();
    expect(result.current.error).toBeNull();
    await act(async () => { await result.current.rescan(); });
    expect(nodeifyProject).not.toHaveBeenCalled();
  });

  it('runs a pass: running while in flight, report on success, onDone fired for the refetch', async () => {
    let resolve;
    nodeifyProject.mockReturnValue(new Promise((r) => { resolve = r; }));
    const onDone = vi.fn();
    const { result } = renderHook(() => useNodeify('1', onDone));

    let pending;
    act(() => { pending = result.current.rescan(); });
    await waitFor(() => expect(result.current.running).toBe(true));
    expect(nodeifyProject).toHaveBeenCalledWith('1');
    expect(onDone).not.toHaveBeenCalled();

    await act(async () => { resolve(REPORT); await pending; });
    expect(result.current.running).toBe(false);
    expect(result.current.report).toEqual(REPORT);
    expect(result.current.error).toBeNull();
    expect(onDone).toHaveBeenCalledWith(REPORT);
  });

  it('captures a failure without throwing and keeps the hook usable', async () => {
    nodeifyProject.mockImplementation(() => Promise.reject(new Error('nodeify already running')));
    const { result } = renderHook(() => useNodeify('1'));
    let returned;
    await act(async () => { returned = await result.current.rescan(); });
    expect(returned).toBeNull();
    expect(result.current.error?.message).toBe('nodeify already running');
    expect(result.current.running).toBe(false);

    // a later successful pass clears the error
    nodeifyProject.mockImplementation(() => Promise.resolve(REPORT));
    await act(async () => { await result.current.rescan(); });
    expect(result.current.error).toBeNull();
    expect(result.current.report).toEqual(REPORT);
  });

  it('guards re-entry: a second call while one is in flight does not start another pass', async () => {
    let resolve;
    nodeifyProject.mockReturnValue(new Promise((r) => { resolve = r; }));
    const { result } = renderHook(() => useNodeify('1'));

    let first;
    let second;
    act(() => {
      first = result.current.rescan();
      second = result.current.rescan();
    });
    expect(nodeifyProject).toHaveBeenCalledTimes(1);
    await act(async () => { expect(await second).toBeNull(); });

    await act(async () => { resolve(REPORT); await first; });
    expect(nodeifyProject).toHaveBeenCalledTimes(1);

    // the guard releases: a later pass runs
    nodeifyProject.mockResolvedValue(REPORT);
    await act(async () => { await result.current.rescan(); });
    expect(nodeifyProject).toHaveBeenCalledTimes(2);
  });

  it('reset clears the report and error', async () => {
    nodeifyProject.mockResolvedValue(REPORT);
    const { result } = renderHook(() => useNodeify('1'));
    await act(async () => { await result.current.rescan(); });
    expect(result.current.report).toEqual(REPORT);
    act(() => { result.current.reset(); });
    expect(result.current.report).toBeNull();
    expect(result.current.error).toBeNull();
  });
});
