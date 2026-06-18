// Path: src/services/sessionsCache.js
// File: sessionsCache.js
// Created: 2026-06-12
// Purpose: Module-level dedup cache for per-project session lists, mirroring services/trackingCache. Mounting ProjectHeader + N ProjectCards would otherwise fire N+1 GETs to /projects/{id}/sessions; this collapses to one in-flight fetch per projectId across all subscribers, with a 60s soft TTL and stale-while-revalidate so navigation refreshes "current session" numbers without a flicker to null.
// Caller: hooks/useProjectSessions (the subscription layer); ProjectHeader and ProjectCard via that hook
// Callees: api/sessions (getProjectSessions)
// Data In: projectId (number); subscribe listener callbacks
// Data Out: Cached session list arrays; cache version counter; subscribe/notify primitives
// Last Modified: 2026-06-12

import { getProjectSessions } from '../api/sessions';

export const SESSIONS_CACHE_TTL_MS = 60_000;

const cache = new Map();
const inflight = new Map();
const listeners = new Set();
let version = 0;

function bumpVersion() {
  version = (version + 1) | 0;
  for (const l of listeners) l();
}

function isFresh(entry, now) {
  return entry != null && (now - entry.fetchedAt) < SESSIONS_CACHE_TTL_MS;
}

export function getCachedSessions(projectId) {
  const entry = cache.get(projectId);
  return entry ? entry.data : null;
}

export function getSessionsCacheVersion() {
  return version;
}

export function subscribeSessionsCache(listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function ensureSessionsFetch(projectId) {
  if (projectId == null) return Promise.resolve(null);
  const entry = cache.get(projectId);
  if (isFresh(entry, Date.now())) return Promise.resolve(entry.data);
  if (inflight.has(projectId)) return inflight.get(projectId);
  const promise = getProjectSessions(projectId)
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

export function invalidateProjectSessions(projectId) {
  if (projectId == null) {
    cache.clear();
  } else {
    cache.delete(projectId);
  }
  bumpVersion();
}

export function __resetSessionsCacheForTests() {
  cache.clear();
  inflight.clear();
  listeners.clear();
  version = 0;
}
