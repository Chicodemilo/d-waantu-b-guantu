// Path: src/api/agentMessages.js
// File: agentMessages.js
// Created: 2026-06-24
// Purpose: API wrappers for the project-scoped inter-agent message log (DWB-451; backend DWB-447/448). getAgentMessages returns the paginated newest-first envelope; clearAgentMessages deletes all rows for the project.
// Caller: pages/InterAgentCommsPage.jsx
// Callees: ./client (get, del)
// Data In: projectId, optional { limit, offset } query params
// Data Out: getAgentMessages -> { project_id, total, limit, offset, rows: [...] }; clearAgentMessages -> { deleted: N }
// Last Modified: 2026-06-24

import { get, del } from './client';

// GET paginated, newest-first list of captured inter-agent messages for a
// project. Envelope: { project_id, total, limit, offset, rows }. Each row:
// { id, from_agent_id, from_agent_name, to_agent_id, to_agent_name, body,
//   summary, created_at, dwb_session_id }.
export function getAgentMessages(projectId, params = {}, options = {}) {
  return get(`/projects/${projectId}/agent-messages`, params, options);
}

// DELETE all captured inter-agent messages for a project. Returns { deleted }.
export function clearAgentMessages(projectId) {
  return del(`/projects/${projectId}/agent-messages`);
}
