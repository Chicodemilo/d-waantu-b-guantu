// Path: src/hooks/useAgentsData.js
// File: useAgentsData.js
// Created: 2026-03-29
// Purpose: Fetches agent data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/agents, hooks/usePolling
// Data In: None
// Data Out: Exports useAgentsData hook; sets agents in Zustand store
// Last Modified: 2026-03-29

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
