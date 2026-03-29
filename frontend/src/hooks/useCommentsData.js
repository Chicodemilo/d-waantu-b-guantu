// Path: src/hooks/useCommentsData.js
// File: useCommentsData.js
// Created: 2026-03-29
// Purpose: Fetches comment data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/comments, hooks/usePolling
// Data In: None
// Data Out: Exports useCommentsData hook; sets comments in Zustand store
// Last Modified: 2026-03-29

import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getComments } from '../api/comments';
import usePolling from './usePolling';

function useCommentsData() {
  const setComments = useStore((s) => s.setComments);

  const fetch = useCallback(async () => {
    const data = await getComments();
    setComments(data);
  }, [setComments]);

  usePolling(fetch);
}

export default useCommentsData;
