// Path: src/pages/ProjectAgentsPage.jsx
// File: ProjectAgentsPage.jsx
// Created: 2026-03-29
// Purpose: Lists all agents assigned to a project with TEAM.md panel (when force_team_md enabled) and agent table
// Caller: App.jsx (route: /projects/:id/agents)
// Callees: react-router-dom, ../store/useStore, ../components/common/StatusBadge, ../components/project/TeamMdPanel
// Data In: Route param (id), project and agents from Zustand store
// Data Out: Default export ProjectAgentsPage component
// Last Modified: 2026-04-16

import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import StatusBadge from '../components/common/StatusBadge';
import TeamMdPanel from '../components/project/TeamMdPanel';

function ProjectAgentsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const agents = useStore((s) => s.getAgentsByProject(id));

  return (
    <div>
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; Back to project</Link>
        <span>{project ? `${project.prefix} Team` : 'Team'}</span>
      </div>
      {project?.force_team_md && (
        <div className="team-md-panel__wrapper">
          <TeamMdPanel projectId={id} />
        </div>
      )}
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Description</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => (
            <tr key={agent.id} className="data-table__row--clickable">
              <td>
                <Link to={`/projects/${id}/agents/${agent.id}`}>
                  {agent.name}
                </Link>
              </td>
              <td>{agent.role}</td>
              <td>{agent.description}</td>
              <td>
                <StatusBadge status={agent.is_active ? 'active' : 'inactive'} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {agents.length === 0 && (
        <div className="empty-state">No agents assigned to this project</div>
      )}
    </div>
  );
}

export default ProjectAgentsPage;
