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
