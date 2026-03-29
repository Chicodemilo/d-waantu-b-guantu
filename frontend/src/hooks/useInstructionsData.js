// Path: src/hooks/useInstructionsData.js
// File: useInstructionsData.js
// Created: 2026-03-29
// Purpose: Fetches instruction data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/instructions, hooks/usePolling
// Data In: None
// Data Out: Exports useInstructionsData hook; sets instructions in Zustand store
// Last Modified: 2026-03-29

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
