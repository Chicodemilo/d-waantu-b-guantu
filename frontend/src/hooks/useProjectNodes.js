// Path: src/hooks/useProjectNodes.js
// File: useProjectNodes.js
// Created: 2026-09-15
// Purpose: Fetch lifecycle for a project's node index (DWB-534). Loads GET /projects/{id}/nodes once per project id with an AbortController on unmount/id change, exposes loading/error/reload, and returns the raw weight-ordered rows plus a stable pointer total. The list is large (3.6k rows, 69k pointers on project 1) so it is fetched once, not polled.
// Caller: pages/NodesPage.jsx
// Callees: react (useState, useEffect, useCallback, useMemo), api/nodes (getProjectNodes)
// Data In: projectId (route param string or number)
// Data Out: { nodes: NodeRead[], pointerTotal: number, loading: boolean, error: Error|null, reload: fn }
// Last Modified: 2026-09-15

import { useState, useEffect, useCallback, useMemo } from 'react';
import { getProjectNodes } from '../api/nodes';

export default function useProjectNodes(projectId) {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (projectId == null || projectId === '') {
      setNodes([]);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    getProjectNodes(projectId, {}, { signal: controller.signal })
      .then((rows) => {
        if (!cancelled) setNodes(Array.isArray(rows) ? rows : []);
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError') return;
        setError(err);
        setNodes([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [projectId, tick]);

  const pointerTotal = useMemo(
    () => nodes.reduce((sum, n) => sum + (Array.isArray(n.pointers) ? n.pointers.length : 0), 0),
    [nodes]
  );

  return { nodes, pointerTotal, loading, error, reload };
}
