// Path: src/hooks/useNodeify.js
// File: useNodeify.js
// Created: 2026-09-15
// Purpose: Rescan lifecycle for the nodes page (DWB-551). Wraps POST /projects/{id}/nodeify: exposes running, the last NodeifyResponse report, and the error text, and guards re-entry with a ref so a double click (or a click landing before the disabled state paints) can never start a second pass, which the backend 500s on. Resolves with the report so the caller can refetch the cloud; never throws to the caller.
// Caller: pages/NodesPage.jsx, components/nodes/ExclusionsManager.jsx (DWB-552)
// Callees: react (useState, useRef, useCallback), api/nodes (nodeifyProject)
// Data In: projectId (route param string or number), optional onDone callback fired after a successful pass
// Data Out: { rescan: fn -> Promise<report|null>, running: boolean, report: NodeifyResponse|null, error: Error|null, reset: fn }
// Last Modified: 2026-09-15

import { useState, useRef, useCallback } from 'react';
import { nodeifyProject } from '../api/nodes';

export default function useNodeify(projectId, onDone) {
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  // Re-entry guard: state updates are async, so a second click in the same tick
  // would otherwise slip past `running`.
  const inFlight = useRef(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const rescan = useCallback(async () => {
    if (inFlight.current || projectId == null) return null;
    inFlight.current = true;
    setRunning(true);
    setError(null);
    try {
      const result = await nodeifyProject(projectId);
      setReport(result);
      if (onDoneRef.current) onDoneRef.current(result);
      return result;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      inFlight.current = false;
      setRunning(false);
    }
  }, [projectId]);

  const reset = useCallback(() => {
    setReport(null);
    setError(null);
  }, []);

  return { rescan, running, report, error, reset };
}
