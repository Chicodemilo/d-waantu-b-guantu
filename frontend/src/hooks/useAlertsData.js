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
