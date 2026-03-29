import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getInstructions } from '../api/instructions';
import usePolling from './usePolling';

function useInstructionsData() {
  const setInstructions = useStore((s) => s.setInstructions);

  const fetch = useCallback(async () => {
    const data = await getInstructions();
    setInstructions(data);
  }, [setInstructions]);

  usePolling(fetch);
}

export default useInstructionsData;
