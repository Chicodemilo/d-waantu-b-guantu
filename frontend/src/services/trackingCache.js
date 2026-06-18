// Path: src/services/trackingCache.js
// File: trackingCache.js
// Created: 2026-06-12
// Purpose: Module-level dedup cache for tracking summaries with a soft TTL. Dashboard previously fired one fetch per (component, project) pair (3 components x N projects = 16+ calls on mount). This collapses to one in-flight fetch per projectId across all subscribers, while a 60s TTL keeps token/time numbers fresh on subsequent navigation. Stale entries are served while a background refetch is in flight (no flicker to null).
// Caller: hooks/useTrackingSummary (the subscription layer); dashboard components via that hook
// Callees: services/tracking (getTrackingSummary)
// Data In: projectId (number); subscribe listener callbacks
// Data Out: Cached summary objects; cache version counter; subscribe/notify primitives
// Last Modified: 2026-06-12

import { getTrackingSummary } from './tracking';

export const TRACKING_CACHE_TTL_MS = 60_000;

const cache = new Map();
const inflight = new Map();
const listeners = new Set();
let version = 0;

function bumpVersion() {
  version = (version + 1) | 0;
  for (const l of listeners) l();
}

function isFresh(entry, now) {
  return entry != null && (now - entry.fetchedAt) < TRACKING_CACHE_TTL_MS;
}

export function getCachedSummary(projectId) {
  const entry = cache.get(projectId);
  return entry ? entry.data : null;
}

export function getCacheVersion() {
  return version;
}

export function subscribeTrackingCache(listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function ensureTrackingFetch(projectId) {
  if (projectId == null) return Promise.resolve(null);
  const entry = cache.get(projectId);
  if (isFresh(entry, Date.now())) return Promise.resolve(entry.data);
  if (inflight.has(projectId)) return inflight.get(projectId);
  const promise = getTrackingSummary(projectId)
    .then((data) => {
      cache.set(projectId, { data, fetchedAt: Date.now() });
      inflight.delete(projectId);
      bumpVersion();
      return data;
    })
    .catch((err) => {
      inflight.delete(projectId);
      throw err;
    });
  inflight.set(projectId, promise);
  return promise;
}

export function invalidateTrackingSummary(projectId) {
  if (projectId == null) {
    cache.clear();
  } else {
    cache.delete(projectId);
  }
  bumpVersion();
}

// Test-only helper. Wipes all module-level state so vitest cases start clean.
export function __resetTrackingCacheForTests() {
  cache.clear();
  inflight.clear();
  listeners.clear();
  version = 0;
}
