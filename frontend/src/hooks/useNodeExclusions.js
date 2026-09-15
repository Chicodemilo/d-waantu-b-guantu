// Path: src/hooks/useNodeExclusions.js
// File: useNodeExclusions.js
// Created: 2026-09-15
// Purpose: List + add + delete lifecycle for a project's node scan exclusions (DWB-552). Loads the rows once per project, exposes add and remove that resolve to {ok, error} rather than throwing so the modal can render the server's own detail text (400 empty/absolute/traversing, 409 duplicate, 404 already gone), and keeps the list in sync locally so a successful write does not need a refetch.
// Caller: components/nodes/ExclusionsManager.jsx
// Callees: react (useState, useEffect, useCallback), api/nodeExclusions
// Data In: projectId, enabled (skip loading while the modal is closed)
// Data Out: { rows, loading, error, adding, add(pattern), remove(id), refresh }
// Last Modified: 2026-09-15

import { useState, useEffect, useCallback } from 'react';
import {
  getNodeExclusions,
  createNodeExclusion,
  deleteNodeExclusion,
} from '../api/nodeExclusions';

function sortRows(rows) {
  return [...rows].sort((a, b) => (a.pattern || '').localeCompare(b.pattern || ''));
}

export default function useNodeExclusions(projectId, enabled = true) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!enabled || projectId == null) return undefined;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    getNodeExclusions(projectId, { signal: controller.signal })
      .then((data) => {
        if (!cancelled) setRows(sortRows(Array.isArray(data) ? data : []));
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError') return;
        setError(err);
        setRows([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [projectId, enabled, tick]);

  const add = useCallback(async (pattern) => {
    const trimmed = (pattern || '').trim();
    if (trimmed === '') return { ok: false, error: 'pattern must not be empty' };
    setAdding(true);
    try {
      const created = await createNodeExclusion(projectId, trimmed);
      if (created) setRows((prev) => sortRows([...prev, created]));
      return { ok: true, row: created };
    } catch (err) {
      return { ok: false, error: err?.message || 'could not add exclusion' };
    } finally {
      setAdding(false);
    }
  }, [projectId]);

  const remove = useCallback(async (exclusionId) => {
    try {
      await deleteNodeExclusion(projectId, exclusionId);
      setRows((prev) => prev.filter((r) => r.id !== exclusionId));
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err?.message || 'could not delete exclusion' };
    }
  }, [projectId]);

  return { rows, loading, error, adding, add, remove, refresh };
}
