import { useEffect, useRef } from 'react';
import useStore from '../store/useStore';
import { getStatus } from '../api/status';
import { POLLING_ACTIVE_INTERVAL, POLLING_IDLE_INTERVAL } from '../config';

function usePolling(fetchFn, deps = []) {
  const intervalRef = useRef(null);
  const setPollingInterval = useStore((s) => s.setPollingInterval);
  const setPollingActive = useStore((s) => s.setPollingActive);
  const updateLastPolled = useStore((s) => s.updateLastPolled);

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      if (cancelled) return;

      try {
        const status = await getStatus();
        const interval =
          status.active_agents > 0 || status.in_progress_tickets > 0
            ? POLLING_ACTIVE_INTERVAL
            : POLLING_IDLE_INTERVAL;
        setPollingInterval(interval);
        setPollingActive(true);

        await fetchFn();
        updateLastPolled();

        if (!cancelled) {
          intervalRef.current = setTimeout(tick, interval);
        }
      } catch {
        setPollingActive(false);
        if (!cancelled) {
          intervalRef.current = setTimeout(tick, POLLING_IDLE_INTERVAL);
        }
      }
    }

    tick();

    return () => {
      cancelled = true;
      if (intervalRef.current) clearTimeout(intervalRef.current);
    };
  }, deps);
}

export default usePolling;
