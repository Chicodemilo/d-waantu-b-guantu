// Path: src/hooks/useTrackingSummary.js
// File: useTrackingSummary.js
// Created: 2026-06-12
// Purpose: React hook layer over services/trackingCache. Components subscribe to a shared cache; first mount per projectId triggers the fetch, subsequent mounts (and sibling components) reuse it. Replaces the per-component useEffect+Promise.all pattern that produced 16+ parallel fetches on dashboard load.
// Caller: dashboard components (ProjectCard, CrossProjectSummary, TimeTokens) and any future tracking-summary consumer
// Callees: services/trackingCache (ensure/subscribe/getCached/getCacheVersion)
// Data In: projectId (number) or projectIds (number[])
// Data Out: summary object or null for the singular hook; { [id]: summary | null } map for the plural hook
// Last Modified: 2026-06-12

import { useEffect, useMemo, useSyncExternalStore } from 'react';
import {
  ensureTrackingFetch,
  getCachedSummary,
  getCacheVersion,
  subscribeTrackingCache,
} from '../services/trackingCache';

export function useTrackingSummary(projectId) {
  useSyncExternalStore(subscribeTrackingCache, getCacheVersion);

  useEffect(() => {
    if (projectId == null) return;
    ensureTrackingFetch(projectId).catch(() => {});
  }, [projectId]);

  return projectId == null ? null : getCachedSummary(projectId);
}

export function useTrackingSummaries(projectIds) {
  const key = (projectIds || []).join(',');
  const cacheVersion = useSyncExternalStore(subscribeTrackingCache, getCacheVersion);

  useEffect(() => {
    if (!projectIds || projectIds.length === 0) return;
    for (const id of projectIds) {
      ensureTrackingFetch(id).catch(() => {});
    }
  }, [key]);

  return useMemo(() => {
    const out = {};
    if (!projectIds) return out;
    for (const id of projectIds) out[id] = getCachedSummary(id);
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, cacheVersion]);
}
