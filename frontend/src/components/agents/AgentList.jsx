// Path: src/components/agents/AgentList.jsx
// File: AgentList.jsx
// Created: 2026-03-29
// Purpose: Renders a list of agent cards linked to their detail pages across active projects
// Caller: DashboardPage.jsx
// Callees: react-router-dom (Link), useStore, agents.css
// Data In: None (reads agents, projectAgents, projects from store)
// Data Out: default export AgentList component
// Last Modified: 2026-03-29

import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
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

  return (
    <div className="agent-list">
      {entries.map(({ key, agent, project }) => (
        <Link key={key} to={`/projects/${project.id}/agents/${agent.id}`} className="agent-card">
          <div className="agent-card__header">
            <span className="agent-card__name">{project.prefix.toLowerCase()}/{agent.name}/{agent.role}</span>
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
