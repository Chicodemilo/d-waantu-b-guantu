// Path: src/__tests__/logger.test.js
// File: logger.test.js
// Created: 2026-06-10
// Purpose: Vitest coverage for services/logger (DWB-371) - asserts enqueue shape (level/category/message/route/occurred_at), context_json carriage, unserializable-context fallback, 64-char category truncation, batch-cap flush at MAX_BATCH, in-test no-fetch contract (the suite would otherwise spam /api/client-logs), and the loop-guard contract that logger.error swallows exceptions in its own enqueue path.
// Caller: vitest test runner
// Callees: ../services/logger, vitest
// Data In: None (records built inline)
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, beforeEach, afterAll, vi } from 'vitest';
import { log, __resetForTests, __peekQueueForTests } from '../services/logger';

describe('logger', () => {
  let fetchSpy;

  beforeEach(() => {
    __resetForTests();
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve({ ok: true, status: 201 }));
  });

  afterAll(() => {
    if (fetchSpy) fetchSpy.mockRestore();
  });

  it('enqueues records with level, category, message, route, occurred_at', () => {
    log.info('fetch', 'GET /projects 200 12ms');
    const queue = __peekQueueForTests();
    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({
      level: 'info',
      category: 'fetch',
      message: 'GET /projects 200 12ms',
    });
    expect(queue[0].route).toBeDefined();
    expect(queue[0].occurred_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });

  it('attaches context_json when context is provided and serializable', () => {
    log.debug('fetch', 'GET /x', { ms: 47, status: 200 });
    const [rec] = __peekQueueForTests();
    expect(rec.context_json).toEqual({ ms: 47, status: 200 });
  });

  it('replaces unserializable context with { unserializable: true }', () => {
    const cyclic = {};
    cyclic.self = cyclic;
    log.warn('fetch.fail', 'broken', cyclic);
    const [rec] = __peekQueueForTests();
    expect(rec.context_json).toEqual({ unserializable: true });
  });

  it('truncates long categories to 64 chars', () => {
    const longCat = 'a'.repeat(100);
    log.info(longCat, 'msg');
    const [rec] = __peekQueueForTests();
    expect(rec.category).toHaveLength(64);
  });

  it('does not invoke window.fetch in test mode (IS_TEST drains silently)', () => {
    for (let i = 0; i < 60; i++) log.info('fetch', `msg ${i}`);
    expect(fetchSpy).not.toHaveBeenCalled();
    // Cap-hit triggers a synchronous drain, so the queue ends below the cap.
    expect(__peekQueueForTests().length).toBeLessThan(60);
  });

  it('loop-guard: enqueue swallows internal errors silently', () => {
    expect(() => log.error('render', null, undefined)).not.toThrow();
    expect(() => log.error('render', 'msg', { ok: true })).not.toThrow();
  });

  it('all four levels enqueue with the correct level value', () => {
    log.debug('c', 'd');
    log.info('c', 'i');
    log.warn('c', 'w');
    log.error('c', 'e');
    const queue = __peekQueueForTests();
    expect(queue.map((r) => r.level)).toEqual(['debug', 'info', 'warn', 'error']);
  });
});
