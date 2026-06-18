// Path: src/__tests__/trackingCache.test.js
// File: trackingCache.test.js
// Created: 2026-06-12
// Purpose: Vitest coverage for services/trackingCache - dedup of concurrent same-id callers (one underlying fetch), no refetch within TTL, soft TTL refetch with stale-served-during-refetch (no flicker), invalidateTrackingSummary forces refetch, rejection releases inflight slot.
// Caller: vitest test runner
// Callees: ../services/trackingCache, ../services/tracking (mocked)
// Data In: None (records built inline)
// Data Out: Test assertions
// Last Modified: 2026-06-12

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('../services/tracking', () => ({
  getTrackingSummary: vi.fn(),
}));

import { getTrackingSummary } from '../services/tracking';
import {
  ensureTrackingFetch,
  getCachedSummary,
  invalidateTrackingSummary,
  subscribeTrackingCache,
  TRACKING_CACHE_TTL_MS,
  __resetTrackingCacheForTests,
} from '../services/trackingCache';

describe('trackingCache', () => {
  beforeEach(() => {
    __resetTrackingCacheForTests();
    getTrackingSummary.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('dedupes concurrent in-flight requests for the same projectId', async () => {
    let resolveFetch;
    getTrackingSummary.mockImplementation(
      () => new Promise((resolve) => { resolveFetch = resolve; })
    );

    const a = ensureTrackingFetch(7);
    const b = ensureTrackingFetch(7);
    const c = ensureTrackingFetch(7);

    expect(getTrackingSummary).toHaveBeenCalledTimes(1);

    resolveFetch({ project_total: { tokens: 100 } });
    const [ra, rb, rc] = await Promise.all([a, b, c]);
    expect(ra).toBe(rb);
    expect(rb).toBe(rc);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);
  });

  it('returns cached value without refetching after resolution', async () => {
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 42 } });
    await ensureTrackingFetch(3);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);

    await ensureTrackingFetch(3);
    await ensureTrackingFetch(3);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);

    expect(getCachedSummary(3)).toEqual({ project_total: { tokens: 42 } });
  });

  it('fires once per distinct projectId', async () => {
    getTrackingSummary.mockResolvedValue({ project_total: { tokens: 0 } });
    await Promise.all([
      ensureTrackingFetch(1),
      ensureTrackingFetch(2),
      ensureTrackingFetch(3),
      ensureTrackingFetch(1),
      ensureTrackingFetch(2),
    ]);
    expect(getTrackingSummary).toHaveBeenCalledTimes(3);
  });

  it('notifies subscribers when a fetch resolves', async () => {
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 9 } });
    const listener = vi.fn();
    const unsubscribe = subscribeTrackingCache(listener);
    await ensureTrackingFetch(5);
    expect(listener).toHaveBeenCalled();
    unsubscribe();
  });

  it('invalidate forces a refetch on the next ensure call', async () => {
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 1 } });
    await ensureTrackingFetch(8);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);

    invalidateTrackingSummary(8);
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 2 } });
    await ensureTrackingFetch(8);
    expect(getTrackingSummary).toHaveBeenCalledTimes(2);
    expect(getCachedSummary(8)).toEqual({ project_total: { tokens: 2 } });
  });

  it('releases inflight slot on rejection so a retry can refetch', async () => {
    getTrackingSummary.mockRejectedValueOnce(new Error('boom'));
    await expect(ensureTrackingFetch(11)).rejects.toThrow('boom');

    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 5 } });
    const result = await ensureTrackingFetch(11);
    expect(result).toEqual({ project_total: { tokens: 5 } });
    expect(getTrackingSummary).toHaveBeenCalledTimes(2);
  });

  it('does NOT refetch when the cached entry is still within TTL', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 1 } });
    await ensureTrackingFetch(20);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);

    // Advance well within TTL.
    vi.setSystemTime(new Date(Date.now() + TRACKING_CACHE_TTL_MS - 1));
    await ensureTrackingFetch(20);
    await ensureTrackingFetch(20);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);
  });

  it('refetches exactly once when the cached entry is older than TTL', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 10 } });
    await ensureTrackingFetch(21);
    expect(getTrackingSummary).toHaveBeenCalledTimes(1);

    // Advance past TTL.
    vi.setSystemTime(new Date(Date.now() + TRACKING_CACHE_TTL_MS + 1));
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 20 } });

    // Three concurrent ensure() calls past TTL should produce exactly one
    // additional fetch (the dedup-during-refetch contract still holds).
    await Promise.all([
      ensureTrackingFetch(21),
      ensureTrackingFetch(21),
      ensureTrackingFetch(21),
    ]);
    expect(getTrackingSummary).toHaveBeenCalledTimes(2);
    expect(getCachedSummary(21)).toEqual({ project_total: { tokens: 20 } });
  });

  it('serves the stale value while a TTL refetch is in flight (no flicker)', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    getTrackingSummary.mockResolvedValueOnce({ project_total: { tokens: 100 } });
    await ensureTrackingFetch(22);
    expect(getCachedSummary(22)).toEqual({ project_total: { tokens: 100 } });

    vi.setSystemTime(new Date(Date.now() + TRACKING_CACHE_TTL_MS + 1));

    let resolveRefetch;
    getTrackingSummary.mockImplementationOnce(
      () => new Promise((resolve) => { resolveRefetch = resolve; })
    );
    const refetchPromise = ensureTrackingFetch(22);

    // Mid-flight: getCachedSummary must still return the previous value so
    // subscribers see the old number rather than a flicker to null.
    expect(getCachedSummary(22)).toEqual({ project_total: { tokens: 100 } });

    resolveRefetch({ project_total: { tokens: 200 } });
    await refetchPromise;
    expect(getCachedSummary(22)).toEqual({ project_total: { tokens: 200 } });
  });
});
