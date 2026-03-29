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
