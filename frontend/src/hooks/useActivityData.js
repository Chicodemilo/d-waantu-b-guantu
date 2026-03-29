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
