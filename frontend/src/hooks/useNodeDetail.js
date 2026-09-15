// Path: src/hooks/useNodeDetail.js
// File: useNodeDetail.js
// Created: 2026-09-15
// Purpose: Detail + neighbor-hop lifecycle for the node overlay (DWB-535). Holds the node currently shown (seeded from the clicked cloud node), fetches GET /projects/{id}/nodes/match?text=<tag> to pull that node's full pointers and derived neighbors, and exposes hop(neighbor) which swaps the shown node in place and refetches. Keeps a trail of hops so the consumer can render a breadcrumb and step back. AbortController cancels in-flight fetches on hop/unmount.
// Caller: components/nodes/NodeDetail.jsx
// Callees: react (useState, useEffect, useCallback, useRef), api/nodes (matchProjectNodes)
// Data In: projectId, seed node ({id, tag, weight, pointers?})
// Data Out: { node, pointers, neighbors, loading, error, trail, hop(fn), back(fn) }
// Last Modified: 2026-09-15

import { useState, useEffect, useCallback, useRef } from 'react';
import { matchProjectNodes } from '../api/nodes';

function pickMatch(response, node) {
  const list = Array.isArray(response?.nodes) ? response.nodes : [];
  return list.find((n) => n.id === node.id) || list.find((n) => n.tag === node.tag) || null;
}

export default function useNodeDetail(projectId, seed) {
  const [trail, setTrail] = useState(seed ? [seed] : []);
  const [detail, setDetail] = useState({ pointers: null, neighbors: null });
  const [loading, setLoading] = useState(Boolean(seed));
  const [error, setError] = useState(null);
  const seedIdRef = useRef(seed ? seed.id : null);

  // A new seed (different node clicked while open, or reopened) restarts the trail.
  useEffect(() => {
    if (!seed) return;
    if (seedIdRef.current !== seed.id || trail.length === 0) {
      seedIdRef.current = seed.id;
      setTrail([seed]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  const node = trail.length ? trail[trail.length - 1] : null;

  useEffect(() => {
    if (!node || projectId == null) return undefined;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail({ pointers: Array.isArray(node.pointers) ? node.pointers : null, neighbors: null });
    matchProjectNodes(projectId, node.tag, { signal: controller.signal })
      .then((res) => {
        if (cancelled) return;
        const hit = pickMatch(res, node);
        setDetail({
          pointers: hit ? hit.pointers || [] : (Array.isArray(node.pointers) ? node.pointers : []),
          neighbors: hit ? hit.neighbors || [] : [],
        });
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError') return;
        setError(err);
        setDetail((d) => ({ pointers: d.pointers || [], neighbors: [] }));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [projectId, node?.id, node?.tag]);

  const hop = useCallback((neighbor) => {
    if (!neighbor) return;
    setTrail((t) => [...t, { id: neighbor.id, tag: neighbor.tag, weight: neighbor.weight }]);
  }, []);

  const back = useCallback(() => {
    setTrail((t) => (t.length > 1 ? t.slice(0, -1) : t));
  }, []);

  return {
    node,
    pointers: detail.pointers,
    neighbors: detail.neighbors,
    loading,
    error,
    trail,
    hop,
    back,
  };
}
