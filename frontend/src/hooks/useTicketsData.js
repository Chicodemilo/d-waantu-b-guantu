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
