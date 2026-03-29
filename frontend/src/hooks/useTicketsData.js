// Path: src/hooks/useTicketsData.js
// File: useTicketsData.js
// Created: 2026-03-29
// Purpose: Fetches ticket data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/tickets, hooks/usePolling
// Data In: None
// Data Out: Exports useTicketsData hook; sets tickets in Zustand store
// Last Modified: 2026-03-29

import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getTickets } from '../api/tickets';
import usePolling from './usePolling';

function useTicketsData() {
  const setTickets = useStore((s) => s.setTickets);

  const fetch = useCallback(async () => {
    const data = await getTickets();
    setTickets(data);
  }, [setTickets]);

  usePolling(fetch);
}

export default useTicketsData;
