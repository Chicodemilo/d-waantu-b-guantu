// Path: src/pages/ProjectAgentsPage.jsx
// File: ProjectAgentsPage.jsx
// Created: 2026-03-29
// Purpose: Team page — TEAM.md panel, deploy playbooks button, agent roster table, and playbook inspector
// Caller: App.jsx (route: /projects/:id/agents)
// Callees: react, react-router-dom, ../store/useStore, ../api/projects (deployPlaybooks), ../components/common/StatusBadge, ../components/project/TeamMdPanel, ../components/project/PlaybookInspector, ../styles/docs.css
// Data In: Route param (id), project and agents from Zustand store
// Data Out: Default export ProjectAgentsPage component
// Last Modified: 2026-04-16

import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { deployPlaybooks } from '../api/projects';
import StatusBadge from '../components/common/StatusBadge';
import TeamMdPanel from '../components/project/TeamMdPanel';
import PlaybookInspector from '../components/project/PlaybookInspector';
import '../styles/docs.css';

function ProjectAgentsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const agents = useStore((s) => s.getAgentsByProject(id));
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState(null);

  const handleDeploy = async () => {
    setDeploying(true);
    setDeployResult(null);
    try {
      await deployPlaybooks(id);
      setDeployResult('done');
    } catch {
      setDeployResult('error');
    } finally {
      setDeploying(false);
    }
  };

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
      {project?.repo_path && (
        <div className="team-deploy">
          <button
            className="sync-btn"
            onClick={handleDeploy}
            disabled={deploying}
          >
            {deploying ? '$ deploying...' : '$ deploy playbooks'}
          </button>
          <span className="tooltip-trigger">
            ?
            <span className="tooltip-content">
              Deploys master playbooks from DWB's docs/ folder into this project's .claude/ directory. Includes Team Lead, PM, and Worker playbooks — giving all agents their operating procedures for this project.
            </span>
          </span>
          {deployResult === 'done' && <span className="sync-btn__status">{'\u2713'} deployed</span>}
          {deployResult === 'error' && <span className="sync-btn__status" style={{ color: 'var(--red)' }}>deploy failed</span>}
        </div>
      )}
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Role</th>
            <th>Description</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => {
            const type = agent.role === 'team-lead' ? 'TL'
              : agent.role === 'pm' ? 'PM'
              : 'Worker';
            return (
            <tr key={agent.id} className="data-table__row--clickable">
              <td>
                <Link to={`/projects/${id}/agents/${agent.id}`}>
                  {agent.name}
                </Link>
              </td>
              <td>{type}</td>
              <td>{agent.role}</td>
              <td>{agent.description}</td>
              <td>
                <StatusBadge status={agent.is_active ? 'active' : 'inactive'} />
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
      {agents.length === 0 && (
        <div className="empty-state">No team members assigned to this project</div>
      )}
      {project?.repo_path && (
        <div className="playbook-inspector__wrapper">
          <PlaybookInspector projectId={id} />
        </div>
      )}
    </div>
  );
}

export default ProjectAgentsPage;
