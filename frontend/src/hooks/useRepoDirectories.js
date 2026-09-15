// Path: src/hooks/useRepoDirectories.js
// File: useRepoDirectories.js
// Created: 2026-09-15
// Purpose: One-level repo directory browsing for the exclusions picker (DWB-552 over Stan's DWB-553 endpoint). Holds the current repo-relative parent, loads its child directories, and exposes open/up/goTo for navigation plus the breadcrumb segments derived from the parent the server echoes back. Errors (400 absolute or traversing, 404 missing) surface as the server's own detail text; a failed navigation leaves the previous listing in place rather than blanking the panel.
// Caller: components/nodes/DirectoryBrowser.jsx
// Callees: react (useState, useEffect, useMemo, useCallback), api/nodeExclusions (getRepoDirectories)
// Data In: projectId, enabled (skip while the panel is collapsed)
// Data Out: { parent, directories, crumbs, loading, error, open(path), up(), goTo(path) }
// Last Modified: 2026-09-15

import { useState, useEffect, useMemo, useCallback } from 'react';
import { getRepoDirectories } from '../api/nodeExclusions';

export default function useRepoDirectories(projectId, enabled = true) {
  const [parent, setParent] = useState('');
  const [directories, setDirectories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!enabled || projectId == null) return undefined;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepoDirectories(projectId, parent, { signal: controller.signal })
      .then((data) => {
        if (cancelled) return;
        setDirectories(Array.isArray(data?.directories) ? data.directories : []);
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError') return;
        // Keep the previous listing on screen: a failed hop should not blank the panel.
        setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [projectId, parent, enabled]);

  const crumbs = useMemo(() => {
    if (!parent) return [];
    const parts = parent.split('/').filter(Boolean);
    return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }));
  }, [parent]);

  const open = useCallback((path) => setParent(path), []);
  const goTo = useCallback((path) => setParent(path || ''), []);
  const up = useCallback(() => {
    setParent((p) => {
      if (!p) return '';
      const parts = p.split('/').filter(Boolean);
      parts.pop();
      return parts.join('/');
    });
  }, []);

  return { parent, directories, crumbs, loading, error, open, up, goTo };
}
