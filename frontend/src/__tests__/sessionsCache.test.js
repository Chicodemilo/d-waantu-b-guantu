// Path: src/__tests__/sessionsCache.test.js
// File: sessionsCache.test.js
// Created: 2026-06-12
// Purpose: Vitest coverage for services/sessionsCache. Mirrors the trackingCache contract: concurrent same-id callers share one fetch, no refetch within TTL, soft TTL refetch with stale-while-revalidate (no flicker), invalidateProjectSessions forces a refetch.
// Caller: vitest test runner
// Callees: ../services/sessionsCache, ../api/sessions (mocked)
// Data In: None (records built inline)
// Data Out: Test assertions
// Last Modified: 2026-06-12

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

import { getProjectSessions } from '../api/sessions';
import {
  ensureSessionsFetch,
  getCachedSessions,
  invalidateProjectSessions,
  SESSIONS_CACHE_TTL_MS,
  __resetSessionsCacheForTests,
} from '../services/sessionsCache';

describe('sessionsCache', () => {
  beforeEach(() => {
    __resetSessionsCacheForTests();
    getProjectSessions.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('dedupes concurrent in-flight requests for the same projectId', async () => {
    let resolveFetch;
    getProjectSessions.mockImplementation(
      () => new Promise((resolve) => { resolveFetch = resolve; })
    );

    const a = ensureSessionsFetch(7);
    const b = ensureSessionsFetch(7);
    const c = ensureSessionsFetch(7);
    expect(getProjectSessions).toHaveBeenCalledTimes(1);

    resolveFetch([{ id: 42, status: 'open', opened_at: '2026-01-01T00:00:00' }]);
    const [ra, rb, rc] = await Promise.all([a, b, c]);
    expect(ra).toBe(rb);
    expect(rb).toBe(rc);
    expect(getProjectSessions).toHaveBeenCalledTimes(1);
  });

  it('does NOT refetch when the cached entry is still within TTL', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    getProjectSessions.mockResolvedValueOnce([{ id: 1, status: 'open' }]);
    await ensureSessionsFetch(20);
    expect(getProjectSessions).toHaveBeenCalledTimes(1);

    vi.setSystemTime(new Date(Date.now() + SESSIONS_CACHE_TTL_MS - 1));
    await ensureSessionsFetch(20);
    await ensureSessionsFetch(20);
    expect(getProjectSessions).toHaveBeenCalledTimes(1);
  });

  it('refetches exactly once when the cached entry is older than TTL', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    getProjectSessions.mockResolvedValueOnce([{ id: 1, status: 'open' }]);
    await ensureSessionsFetch(21);

    vi.setSystemTime(new Date(Date.now() + SESSIONS_CACHE_TTL_MS + 1));
    getProjectSessions.mockResolvedValueOnce([{ id: 2, status: 'open' }]);
    await Promise.all([
      ensureSessionsFetch(21),
      ensureSessionsFetch(21),
      ensureSessionsFetch(21),
    ]);
    expect(getProjectSessions).toHaveBeenCalledTimes(2);
    expect(getCachedSessions(21)).toEqual([{ id: 2, status: 'open' }]);
  });

  it('serves the stale value while a TTL refetch is in flight (no flicker)', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    getProjectSessions.mockResolvedValueOnce([{ id: 100, status: 'open' }]);
    await ensureSessionsFetch(22);
    expect(getCachedSessions(22)).toEqual([{ id: 100, status: 'open' }]);

    vi.setSystemTime(new Date(Date.now() + SESSIONS_CACHE_TTL_MS + 1));
    let resolveRefetch;
    getProjectSessions.mockImplementationOnce(
      () => new Promise((resolve) => { resolveRefetch = resolve; })
    );
    const p = ensureSessionsFetch(22);
    expect(getCachedSessions(22)).toEqual([{ id: 100, status: 'open' }]);

    resolveRefetch([{ id: 200, status: 'open' }]);
    await p;
    expect(getCachedSessions(22)).toEqual([{ id: 200, status: 'open' }]);
  });

  it('invalidate forces a refetch on the next ensure call', async () => {
    getProjectSessions.mockResolvedValueOnce([{ id: 1 }]);
    await ensureSessionsFetch(8);
    invalidateProjectSessions(8);
    getProjectSessions.mockResolvedValueOnce([{ id: 2 }]);
    await ensureSessionsFetch(8);
    expect(getProjectSessions).toHaveBeenCalledTimes(2);
    expect(getCachedSessions(8)).toEqual([{ id: 2 }]);
  });

  it('releases inflight slot on rejection so a retry can refetch', async () => {
    getProjectSessions.mockRejectedValueOnce(new Error('boom'));
    await expect(ensureSessionsFetch(11)).rejects.toThrow('boom');

    getProjectSessions.mockResolvedValueOnce([{ id: 99 }]);
    const result = await ensureSessionsFetch(11);
    expect(result).toEqual([{ id: 99 }]);
    expect(getProjectSessions).toHaveBeenCalledTimes(2);
  });
});
