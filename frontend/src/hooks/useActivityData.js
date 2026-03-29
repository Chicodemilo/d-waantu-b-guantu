// Path: src/hooks/useActivityData.js
// File: useActivityData.js
// Created: 2026-03-29
// Purpose: Fetches and parses activity log data on a polling interval
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/activityLogs, config, hooks/usePolling
// Data In: None (reads ACTIVITY_LOG_LIMIT from config)
// Data Out: Exports useActivityData hook; sets activityLog in Zustand store
// Last Modified: 2026-03-29

import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getActivityLogs } from '../api/activityLogs';
import { ACTIVITY_LOG_LIMIT } from '../config';
import usePolling from './usePolling';

function parseDetails(item) {
  if (!item.details || typeof item.details !== 'string') return item;
  try {
    return { ...item, details: JSON.parse(item.details) };
  } catch {
    return item;
  }
}

function useActivityData() {
  const setActivityLog = useStore((s) => s.setActivityLog);

  const fetch = useCallback(async () => {
    const data = await getActivityLogs({ limit: ACTIVITY_LOG_LIMIT });
    setActivityLog(data.map(parseDetails));
  }, [setActivityLog]);

  usePolling(fetch);
}

export default useActivityData;
