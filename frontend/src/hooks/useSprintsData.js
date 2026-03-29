// Path: src/hooks/useSprintsData.js
// File: useSprintsData.js
// Created: 2026-03-29
// Purpose: Fetches sprint data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/sprints, hooks/usePolling
// Data In: None
// Data Out: Exports useSprintsData hook; sets sprints in Zustand store
// Last Modified: 2026-03-29

import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getSprints } from '../api/sprints';
import usePolling from './usePolling';

function useSprintsData() {
  const setSprints = useStore((s) => s.setSprints);

  const fetch = useCallback(async () => {
    const data = await getSprints();
    setSprints(data);
  }, [setSprints]);

  usePolling(fetch);
}

export default useSprintsData;
