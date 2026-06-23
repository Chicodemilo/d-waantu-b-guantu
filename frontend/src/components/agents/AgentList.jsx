// Path: src/components/agents/AgentList.jsx
// File: AgentList.jsx
// Created: 2026-03-29
// Purpose: Renders a list of agent cards linked to their detail pages across active projects, each showing the agent's reputation for that project (DWB-435)
// Caller: DashboardPage.jsx
// Callees: react (useState, useEffect), react-router-dom (Link), useStore, api/scores (getProjectScores), agents.css
// Data In: None (reads agents, projectAgents, projects from store; fetches per-project scores)
// Data Out: default export AgentList component
// Last Modified: 2026-06-23

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { getProjectScores } from '../../api/scores';
import '../../styles/agents.css';

function AgentList() {
  const agents = useStore((s) => s.agents);
  const projectAgents = useStore((s) => s.projectAgents);
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');

  const entries = projectAgents.map((pa) => {
    const agent = agents.find((a) => a.id === pa.agent_id);
    const project = projects.find((p) => p.id === pa.project_id);
    if (!agent || !project) return null;
    return { key: `${pa.project_id}-${pa.agent_id}`, agent, project };
  }).filter(Boolean);

  // Reputation is per-(agent, project). Each card is one project+agent pairing,
  // so fetch each shown project's leaderboard once and key reputation by
  // `${projectId}-${agentId}`. Defaults to 0 when the agent is absent.
  const [repByKey, setRepByKey] = useState({});
  const projectIdsKey = [...new Set(entries.map((e) => e.project.id))].sort((a, b) => a - b).join(',');

  useEffect(() => {
    let cancelled = false;
    const projectIds = projectIdsKey ? projectIdsKey.split(',').map(Number) : [];
    if (projectIds.length === 0) {
      setRepByKey({});
      return;
    }
    Promise.all(
      projectIds.map((pid) =>
        getProjectScores(pid)
          .then((rows) => ({ pid, rows: Array.isArray(rows) ? rows : [] }))
          .catch(() => ({ pid, rows: [] }))
      )
    ).then((results) => {
      if (cancelled) return;
      const map = {};
      results.forEach(({ pid, rows }) => {
        rows.forEach((r) => { map[`${pid}-${r.agent_id}`] = r.reputation; });
      });
      setRepByKey(map);
    });
    return () => { cancelled = true; };
  }, [projectIdsKey]);

  return (
    <div className="agent-list">
      {entries.map(({ key, agent, project }) => (
        <Link key={key} to={`/projects/${project.id}/agents/${agent.id}`} className="agent-card">
          <div className="agent-card__header">
            <span className="agent-card__name">{project.prefix.toLowerCase()}/{agent.name}/{agent.role}</span>
            <span className="agent-card__rep">rep {repByKey[`${project.id}-${agent.id}`] ?? 0}</span>
          </div>
          <div className="agent-card__desc">{agent.description}</div>
          <div className="agent-card__status">
            <span
              className={`agent-card__status-dot${agent.is_active ? '' : ' agent-card__status-dot--inactive'}`}
            />
            {agent.is_active ? 'active' : 'inactive'}
          </div>
        </Link>
      ))}
    </div>
  );
}

export default AgentList;
