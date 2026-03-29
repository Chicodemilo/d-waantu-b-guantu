// Path: src/hooks/useEpicsData.js
// File: useEpicsData.js
// Created: 2026-03-29
// Purpose: Fetches epic data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/epics, hooks/usePolling
// Data In: None
// Data Out: Exports useEpicsData hook; sets epics in Zustand store
// Last Modified: 2026-03-29

import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getEpics } from '../api/epics';
import usePolling from './usePolling';

function useEpicsData() {
  const setEpics = useStore((s) => s.setEpics);

  const fetch = useCallback(async () => {
    const data = await getEpics();
    setEpics(data);
  }, [setEpics]);

  usePolling(fetch);
}

export default useEpicsData;
