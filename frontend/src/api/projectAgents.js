// Path: src/api/projectAgents.js
// File: projectAgents.js
// Created: 2026-03-29
// Purpose: API function to fetch project-agent associations
// Caller: hooks/useAppData.js
// Callees: ./client (get)
// Data In: Optional query params for filtering
// Data Out: Array of project-agent association objects from /project-agents endpoint
// Last Modified: 2026-03-29

import { get } from './client';

export function getProjectAgents(params = {}) {
  return get('/project-agents', params);
}
