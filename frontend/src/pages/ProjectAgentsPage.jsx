// Path: src/pages/ProjectAgentsPage.jsx
// File: ProjectAgentsPage.jsx
// Created: 2026-03-29
// Purpose: Team page — tabbed Roster | Scoreboard. Roster tab: deploy playbooks button, agent roster table (with a per-agent reputation Score column, DWB-435), and playbook inspector. Scoreboard tab (DWB-433): full per-project scoring leaderboard.
// Caller: App.jsx (route: /projects/:id/agents)
// Callees: react, react-router-dom, ../store/useStore, ../api/projects (deployPlaybooks), ../api/scores (getProjectScores), ../components/common/StatusBadge, ../components/project/PlaybookInspector, ../components/project/Scoreboard, ../styles/docs.css
// Data In: Route param (id), project and agents from Zustand store
// Data Out: Default export ProjectAgentsPage component
// Last Modified: 2026-06-23

import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { deployPlaybooks } from '../api/projects';
import { getProjectScores } from '../api/scores';
import StatusBadge from '../components/common/StatusBadge';
import PlaybookInspector from '../components/project/PlaybookInspector';
import Scoreboard from '../components/project/Scoreboard';
import '../styles/docs.css';

function ProjectAgentsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const agents = useStore((s) => s.getAgentsByProject(id));
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState(null);
  const [activeTab, setActiveTab] = useState('roster');
  const [repByAgent, setRepByAgent] = useState({});

  useEffect(() => {
    let cancelled = false;
    getProjectScores(id)
      .then((rows) => {
        if (cancelled) return;
        const map = {};
        (Array.isArray(rows) ? rows : []).forEach((r) => { map[r.agent_id] = r.reputation; });
        setRepByAgent(map);
      })
      .catch(() => { if (!cancelled) setRepByAgent({}); });
    return () => { cancelled = true; };
  }, [id]);

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
      <div className="team-tab-bar">
        <button
          className={`team-tab${activeTab === 'roster' ? ' team-tab--active' : ''}`}
          onClick={() => setActiveTab('roster')}
        >
          Roster
        </button>
        <button
          className={`team-tab${activeTab === 'scoreboard' ? ' team-tab--active' : ''}`}
          onClick={() => setActiveTab('scoreboard')}
        >
          Scoreboard
        </button>
      </div>
      {activeTab === 'scoreboard' && <Scoreboard projectId={id} />}
      {activeTab === 'roster' && (
      <>
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
              Deploys master playbooks from DWB's docs/ folder into this project's .claude/ directory.
              <ul className="tooltip-list">
                <li>Overwrites: Team Lead, PM, and Worker playbooks</li>
                <li>Creates (if missing): project rules files for TL, PM, and workers</li>
                <li>Project rules are never overwritten — safe to re-deploy</li>
              </ul>
            </span>
          </span>
          {project.playbooks_deployed_at && (
            <span style={{ color: 'var(--gray-light)', fontSize: '11px' }}>
              last deployed: {(() => {
                const ts = project.playbooks_deployed_at.endsWith('Z') ? project.playbooks_deployed_at : project.playbooks_deployed_at + 'Z';
                const d = new Date(ts);
                return `${d.getMonth() + 1}/${d.getDate()}/${String(d.getFullYear()).slice(2)} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
              })()}
            </span>
          )}
          {deployResult === 'done' && <span className="sync-btn__status">{'\u2713'} deployed</span>}
          {deployResult === 'error' && <span className="sync-btn__status" style={{ color: 'var(--red)' }}>deploy failed</span>}
        </div>
      )}
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th className="agents-table__score">Score</th>
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
              <td className="agents-table__score">{repByAgent[agent.id] ?? 0}</td>
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
      </>
      )}
    </div>
  );
}

export default ProjectAgentsPage;
