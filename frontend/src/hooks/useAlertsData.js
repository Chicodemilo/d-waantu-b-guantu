// Path: src/hooks/useAlertsData.js
// File: useAlertsData.js
// Created: 2026-03-29
// Purpose: Fetches alert data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/alerts, hooks/usePolling
// Data In: None
// Data Out: Exports useAlertsData hook; sets alerts in Zustand store
// Last Modified: 2026-03-29

import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getAlerts } from '../api/alerts';
import usePolling from './usePolling';

function useAlertsData() {
  const setAlerts = useStore((s) => s.setAlerts);

  const fetch = useCallback(async () => {
    const data = await getAlerts();
    setAlerts(data);
  }, [setAlerts]);

  usePolling(fetch);
}

export default useAlertsData;
