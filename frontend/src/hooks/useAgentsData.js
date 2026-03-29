import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getAgents } from '../api/agents';
import usePolling from './usePolling';

function useAgentsData() {
  const setAgents = useStore((s) => s.setAgents);

  const fetch = useCallback(async () => {
    const data = await getAgents();
    setAgents(data);
  }, [setAgents]);

  usePolling(fetch);
}

export default useAgentsData;
