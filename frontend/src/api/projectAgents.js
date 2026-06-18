// Path: src/api/projectAgents.js
// File: projectAgents.js
// Created: 2026-03-29
// Purpose: API wrappers for project-agent associations (raw bridge rows) and the DB-authoritative live roster including last_seen + presumed_live per-agent fields (DWB-387).
// Caller: hooks/useAppData.js, components/project/LiveSessions.jsx
// Callees: ./client (get)
// Data In: Optional query params for filtering; projectId for the roster endpoint
// Data Out: Array of project-agent association objects; project team object { project_id, project_prefix, agents: [{agent_id, name, role, is_active, assigned_at, last_seen, presumed_live}] }
// Last Modified: 2026-06-12

import { get } from './client';

export function getProjectAgents(params = {}) {
  return get('/project-agents', params);
}

export function getProjectTeam(projectId) {
  return get(`/projects/${projectId}/team`);
}
