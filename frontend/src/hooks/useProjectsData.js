import { useCallback } from 'react';
import useStore from '../store/useStore';
import { getProjects } from '../api/projects';
import usePolling from './usePolling';

function useProjectsData() {
  const setProjects = useStore((s) => s.setProjects);

  const fetch = useCallback(async () => {
    const data = await getProjects();
    setProjects(data);
  }, [setProjects]);

  usePolling(fetch);
}

export default useProjectsData;
