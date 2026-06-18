// Path: src/hooks/useProjectSessions.js
// File: useProjectSessions.js
// Created: 2026-06-12
// Purpose: React hook layer over services/sessionsCache. Returns the "current session" for a project: open session if any (status === 'open' or closed_at == null), otherwise the most recently opened closed session. Returns null only if the project has no sessions at all. Mirrors useTrackingSummary.
// Caller: ProjectHeader, ProjectCard
// Callees: services/sessionsCache
// Data In: projectId (number)
// Data Out: session object (open or most-recent-closed) or null
// Last Modified: 2026-06-12

import { useEffect, useMemo, useSyncExternalStore } from 'react';
import {
  ensureSessionsFetch,
  getCachedSessions,
  getSessionsCacheVersion,
  subscribeSessionsCache,
} from '../services/sessionsCache';

function pickCurrentSession(list) {
  if (!Array.isArray(list) || list.length === 0) return null;
  const open = list.find((s) => s.status === 'open' || s.closed_at == null);
  if (open) return open;
  // List is server-ordered by opened_at desc, so list[0] is the most recent.
  return list[0];
}

export function useCurrentSession(projectId) {
  const cacheVersion = useSyncExternalStore(subscribeSessionsCache, getSessionsCacheVersion);

  useEffect(() => {
    if (projectId == null) return;
    ensureSessionsFetch(projectId).catch(() => {});
  }, [projectId]);

  return useMemo(() => {
    if (projectId == null) return null;
    return pickCurrentSession(getCachedSessions(projectId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, cacheVersion]);
}
