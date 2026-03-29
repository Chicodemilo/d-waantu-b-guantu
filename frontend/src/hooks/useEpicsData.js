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
