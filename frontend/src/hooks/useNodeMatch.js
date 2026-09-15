// Path: src/hooks/useNodeMatch.js
// File: useNodeMatch.js
// Created: 2026-09-15
// Purpose: Debounced node match lifecycle for the cloud limiter (DWB-536). Waits delay ms after the last keystroke, then calls GET /projects/{id}/nodes/match?text=<query> and exposes the matched node id set plus the normalized query_tags. An empty or whitespace query short-circuits to "not limiting" (matchIds null) without a request. Each fetch carries an AbortController so a stale response never overwrites a newer query.
// Caller: pages/NodesPage.jsx
// Callees: react (useState, useEffect, useRef), api/nodes (matchProjectNodes)
// Data In: projectId, query (string), delay (ms, default 250)
// Data Out: { matchIds: Set<number>|null, queryTags: string[], loading: boolean, error: Error|null, settledQuery: string }
// Last Modified: 2026-09-15

import { useState, useEffect, useRef } from 'react';
import { matchProjectNodes } from '../api/nodes';

export const NODE_MATCH_DEBOUNCE_MS = 250;

const IDLE = { matchIds: null, queryTags: [], error: null, settledQuery: '' };

export default function useNodeMatch(projectId, query, delay = NODE_MATCH_DEBOUNCE_MS) {
  const [state, setState] = useState(IDLE);
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef(null);

  useEffect(() => {
    const text = (query || '').trim();
    if (controllerRef.current) {
      controllerRef.current.abort();
      controllerRef.current = null;
    }
    if (text === '' || projectId == null) {
      setState(IDLE);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      const controller = new AbortController();
      controllerRef.current = controller;
      matchProjectNodes(projectId, text, { signal: controller.signal })
        .then((res) => {
          if (controller.signal.aborted) return;
          const nodes = Array.isArray(res?.nodes) ? res.nodes : [];
          setState({
            matchIds: new Set(nodes.map((n) => n.id)),
            queryTags: Array.isArray(res?.query_tags) ? res.query_tags : [],
            error: null,
            settledQuery: text,
          });
          setLoading(false);
        })
        .catch((err) => {
          if (controller.signal.aborted || err?.name === 'AbortError') return;
          setState({ matchIds: new Set(), queryTags: [], error: err, settledQuery: text });
          setLoading(false);
        });
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [projectId, query, delay]);

  useEffect(() => () => {
    if (controllerRef.current) controllerRef.current.abort();
  }, []);

  return { ...state, loading };
}
