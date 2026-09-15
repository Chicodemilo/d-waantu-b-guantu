// Path: src/hooks/useNodeConnections.js
// File: useNodeConnections.js
// Created: 2026-09-15 (as useNodeMatch.js, DWB-536; renamed and repurposed in DWB-543)
// Purpose: First-degree connections fetcher for the nodes cloud "+ connections" toggle (DWB-543). When enabled and the client-side substring search matches between 1 and MAX_CONNECTION_MATCHES nodes, calls GET /projects/{id}/nodes/match?text=<tag> once per matched tag (deduped), merges every neighbor id that is not itself a match into a Set, and aborts the whole fan-out when the matches, toggle, or project change. Disabled or over the cap it does nothing and reports an empty set.
// Caller: pages/NodesPage.jsx
// Callees: react (useState, useEffect, useRef), api/nodes (matchProjectNodes)
// Data In: projectId, matches (NodeRead[] currently matched by the search), enabled (bool)
// Data Out: { connectedIds: Set<number>, loading: boolean, error: Error|null, eligible: boolean }
// Last Modified: 2026-09-15 (DWB-543: effect keyed on id signature)

import { useState, useEffect, useRef } from 'react';
import { matchProjectNodes } from '../api/nodes';

export const MAX_CONNECTION_MATCHES = 25;

const EMPTY = new Set();

export function connectionsEligible(matchCount) {
  return matchCount > 0 && matchCount <= MAX_CONNECTION_MATCHES;
}

export default function useNodeConnections(projectId, matches, enabled) {
  const [connectedIds, setConnectedIds] = useState(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const eligible = connectionsEligible(matches ? matches.length : 0);

  // Key the fan-out on the match ids, not the array identity, so a re-render that
  // rebuilds an identical list does not refetch (and cannot loop through setState).
  const signature = matches && matches.length ? matches.map((n) => n.id).join(',') : '';
  const matchesRef = useRef(matches);
  matchesRef.current = matches;

  useEffect(() => {
    const current = matchesRef.current || [];
    if (!enabled || !eligible || projectId == null) {
      setConnectedIds(EMPTY);
      setLoading(false);
      setError(null);
      return undefined;
    }
    const controller = new AbortController();
    const matchIds = new Set(current.map((n) => n.id));
    const tags = [...new Set(current.map((n) => n.tag))];
    setLoading(true);
    setError(null);
    Promise.allSettled(tags.map((tag) => matchProjectNodes(projectId, tag, { signal: controller.signal })))
      .then((results) => {
        if (controller.signal.aborted) return;
        const ids = new Set();
        let firstError = null;
        for (const r of results) {
          if (r.status !== 'fulfilled') {
            if (!firstError && r.reason?.name !== 'AbortError') firstError = r.reason;
            continue;
          }
          for (const node of r.value?.nodes || []) {
            for (const nb of node.neighbors || []) {
              if (!matchIds.has(nb.id)) ids.add(nb.id);
            }
          }
        }
        setConnectedIds(ids);
        setError(firstError);
        setLoading(false);
      });
    return () => {
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, signature, enabled, eligible]);

  return { connectedIds, loading, error, eligible };
}
