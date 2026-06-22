// Path: src/api/scores.js
// File: scores.js
// Created: 2026-06-22
// Purpose: API wrappers for the agent scoring system (epic 28, DWB-424 read API). getProjectScores returns the project leaderboard (already sorted top-first, full roster); getAgentScore returns one agent's reputation/influence/sprint_delta plus the append-only score_event ledger.
// Caller: components/project/LiveSessions.jsx, pages/AgentPage.jsx
// Callees: ./client (get)
// Data In: projectId; agentId + projectId
// Data Out: Array of leaderboard rows { agent_id, agent_name, agent_role, reputation, sprint_delta, influence }; agent score object { agent_id, project_id, reputation, influence, sprint_delta, ledger: [...] }
// Last Modified: 2026-06-22

import { get } from './client';

export function getProjectScores(projectId) {
  return get(`/projects/${projectId}/scores`);
}

export function getAgentScore(agentId, projectId) {
  return get(`/agents/${agentId}/score`, { project_id: projectId });
}
