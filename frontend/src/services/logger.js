// Path: src/services/logger.js
// File: logger.js
// Created: 2026-06-10
// Purpose: Frontend log shipper (DWB-371). Batches structured log records and POSTs them to /api/client-logs so the TL can curl the lifecycle trail without browser-console access. Each call enqueues a record with client-side `occurred_at`, the current `route` (window.location.pathname), and a category/message/context. Flushes on (a) queue >= MAX_BATCH, (b) every FLUSH_INTERVAL_MS, (c) visibilitychange to hidden, (d) beforeunload via sendBeacon. Logger failures never throw, never re-enter the logger, never spam console — they drop silently. Skips network activity in vitest (MODE === 'test') so test runs do not hit the API.
// Caller: api/client.js (fetch lifecycle), components/common/ErrorBoundary.jsx (render exceptions), components/common/RouteLogger.jsx (nav mount/unmount), hooks/useAppData.js (store hydration milestone), anywhere callers need structured backend visibility
// Callees: window.fetch (raw, NOT the instrumented api/client request so we cannot loop), navigator.sendBeacon (unload only), config (API_BASE_URL)
// Data In: log.<level>(category, message, context?) - level enum debug|info|warn|error, category <=64 chars, message string, context optional dict
// Data Out: Side effects only - posts JSON arrays of log records to /api/client-logs. Exports `log` (level-method facade) and `__resetForTests` test hook.
// Last Modified: 2026-06-10

import { API_BASE_URL } from '../config';

const FLUSH_INTERVAL_MS = 1000;
const MAX_BATCH = 50;
const ENDPOINT = `${API_BASE_URL}/client-logs`;
const IS_TEST = typeof import.meta !== 'undefined'
  && import.meta.env
  && import.meta.env.MODE === 'test';

let queue = [];
let timer = null;

function safeContext(context) {
  if (context == null) return undefined;
  try {
    JSON.stringify(context);
    return context;
  } catch {
    return { unserializable: true };
  }
}

function currentRoute() {
  if (typeof window === 'undefined' || !window.location) return '';
  return window.location.pathname || '';
}

function enqueue(level, category, message, context) {
  try {
    const record = {
      level,
      category: String(category || '').slice(0, 64),
      message: String(message == null ? '' : message).slice(0, 4000),
      route: currentRoute(),
      occurred_at: new Date().toISOString(),
    };
    const ctx = safeContext(context);
    if (ctx !== undefined) record.context_json = ctx;
    queue.push(record);
    if (queue.length >= MAX_BATCH) {
      flush();
    } else {
      ensureTimer();
    }
  } catch {
    // Loop guard: anything blows up enqueueing, swallow.
  }
}

function ensureTimer() {
  if (timer != null) return;
  if (typeof setTimeout === 'undefined') return;
  timer = setTimeout(() => {
    timer = null;
    flush();
  }, FLUSH_INTERVAL_MS);
}

function drain() {
  if (queue.length === 0) return [];
  const batch = queue;
  queue = [];
  return batch;
}

function flush() {
  if (IS_TEST) {
    drain();
    return;
  }
  const batch = drain();
  if (batch.length === 0) return;
  try {
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(batch),
      keepalive: true,
    }).catch(() => {
      // Loop guard: dropped on backend failure. No retry, no console, no re-enqueue.
    });
  } catch {
    // Loop guard: never let a logger throw.
  }
}

function flushBeacon() {
  if (IS_TEST) {
    drain();
    return;
  }
  if (queue.length === 0) return;
  try {
    const batch = drain();
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      const blob = new Blob([JSON.stringify(batch)], { type: 'application/json' });
      navigator.sendBeacon(ENDPOINT, blob);
    } else {
      // Fallback: best-effort fetch with keepalive.
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(batch),
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    // Loop guard.
  }
}

if (typeof window !== 'undefined' && !IS_TEST) {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushBeacon();
  });
  window.addEventListener('beforeunload', flushBeacon);
  window.addEventListener('pagehide', flushBeacon);
}

export const log = {
  debug: (category, message, context) => enqueue('debug', category, message, context),
  info: (category, message, context) => enqueue('info', category, message, context),
  warn: (category, message, context) => enqueue('warn', category, message, context),
  error: (category, message, context) => enqueue('error', category, message, context),
};

export function __resetForTests() {
  queue = [];
  if (timer != null) {
    clearTimeout(timer);
    timer = null;
  }
}

export function __peekQueueForTests() {
  return queue.slice();
}

export default log;
