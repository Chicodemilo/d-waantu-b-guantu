// Path: src/api/scores.js
// File: scores.js
// Created: 2026-06-22
// Purpose: API wrappers for the agent scoring system (epic 28, DWB-424 read API; DWB-434 award write). getProjectScores returns the project leaderboard (already sorted top-first, full roster); getAgentScore returns one agent's reputation/influence/sprint_delta plus the append-only score_event ledger; awardScore posts a human carrot/stick (DWB-426 endpoint) for an agent on a project.
// Caller: components/project/LiveSessions.jsx, components/project/Scoreboard.jsx, pages/AgentPage.jsx
// Callees: ./client (get, post)
// Data In: projectId; agentId + projectId; projectId + { agent, delta, reason }
// Data Out: Array of leaderboard rows { agent_id, agent_name, agent_role, reputation, sprint_delta, influence }; agent score object { agent_id, project_id, reputation, influence, sprint_delta, ledger: [...] }; award response { status, event_id, subject_agent_id, subject_name, delta, reputation, sprint_delta, ... }
// Last Modified: 2026-06-23

import { get, post } from './client';

export function getProjectScores(projectId) {
  return get(`/projects/${projectId}/scores`);
}

export function getAgentScore(agentId, projectId) {
  return get(`/agents/${agentId}/score`, { project_id: projectId });
}

// Human carrot/stick (DWB-426 endpoint). `agent` is a name or id, `delta` is
// signed (>0 carrot, <0 stick), `reason` is optional and omitted when blank.
export function awardScore(projectId, { agent, delta, reason }) {
  const body = { agent, delta };
  if (reason && reason.trim()) body.reason = reason.trim();
  return post(`/projects/${projectId}/scores/award`, body);
}
