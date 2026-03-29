// Path: src/hooks/useProjectsData.js
// File: useProjectsData.js
// Created: 2026-03-29
// Purpose: Fetches project data on a polling interval and stores in Zustand
// Caller: None currently (unused hook, superseded by useAppData)
// Callees: react, store/useStore, api/projects, hooks/usePolling
// Data In: None
// Data Out: Exports useProjectsData hook; sets projects in Zustand store
// Last Modified: 2026-03-29

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
