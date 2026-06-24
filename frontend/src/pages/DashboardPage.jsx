// Path: src/pages/DashboardPage.jsx
// File: DashboardPage.jsx
// Created: 2026-03-29
// Purpose: Main dashboard showing project cards, alerts table (read-only), token usage summary, and agent list
// Caller: App.jsx (route: /)
// Callees: react, react-router-dom (useNavigate, Link), ../store/useStore, ../components/dashboard/CrossProjectSummary, ../components/dashboard/ProjectCard, ../components/dashboard/TokenOverview, ../components/agents/AgentList, ../components/dashboard/TokenAudit, ../api/projects, ../styles/dashboard.css
// Data In: Projects, alerts, and agents from Zustand store
// Data Out: Default export DashboardPage component
// Last Modified: 2026-04-17

import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import CrossProjectSummary from '../components/dashboard/CrossProjectSummary';
import ProjectCard from '../components/dashboard/ProjectCard';
import TimeTokens from '../components/dashboard/TimeTokens';
import AgentList from '../components/agents/AgentList';
import TokenAudit from '../components/dashboard/TokenAudit';
import { createProjectFromRepo, seedDemoProject } from '../api/projects';
import '../styles/dashboard.css';

function DashboardPage() {
  const navigate = useNavigate();
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const openAlerts = useStore((s) => s.getSurfacedAlerts()); // DWB-464: surfaced categories only
  const clearAllAlerts = useStore((s) => s.clearAllAlerts);
  const getProject = useStore((s) => s.getProject);
  const [addExpanded, setAddExpanded] = useState(false);
  const [repoPath, setRepoPath] = useState('');
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState(null);
  const [seeding, setSeeding] = useState(false);

  const handleSeedDemo = async () => {
    setSeeding(true);
    try {
      await seedDemoProject();
    } catch {
      // next poll will refresh
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div className="dashboard">
      <div>
        <div className="dashboard__section-title">Summary</div>
        <CrossProjectSummary />
      </div>

      {openAlerts.length > 0 && (
        <div>
          <div className="dashboard__section-title">
            Open Alerts
            <button
              type="button"
              className="dashboard__section-action"
              onClick={clearAllAlerts}
            >
              clear all
            </button>
          </div>
          <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Category</th>
                  <th>Severity</th>
                  <th>Title</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {[...openAlerts].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)).map((alert) => {
                  const proj = getProject(alert.project_id);
                  const severityColor = alert.severity === 'critical' ? 'var(--red)'
                    : alert.severity === 'warning' ? 'var(--yellow)'
                    : 'var(--blue)';
                  return (
                    <tr key={alert.id}>
                      <td>
                        {proj ? (
                          <Link to={`/projects/${proj.id}`}>{proj.prefix}</Link>
                        ) : '\u2014'}
                      </td>
                      <td>
                        {alert.category ? (
                          <span className={`alert-category-badge alert-category-badge--${alert.category}`}>
                            {alert.category}
                          </span>
                        ) : '-'}
                      </td>
                      <td style={{ color: severityColor }}>{alert.severity}</td>
                      <td>{alert.title}</td>
                      <td>{alert.created_at ? new Date(alert.created_at).toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '\u2014'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div>
        <div className="dashboard__section-title">
          Projects
          <button
            className="sync-btn"
            style={{ marginLeft: '16px' }}
            onClick={() => { setAddExpanded(!addExpanded); setAddError(null); }}
          >
            {addExpanded ? '$ cancel' : '$ add project'}
          </button>
          <button
            className="sync-btn"
            style={{ marginLeft: '8px' }}
            onClick={handleSeedDemo}
            disabled={seeding}
          >
            {seeding ? '$ seeding...' : '$ seed demo project'}
          </button>
        </div>
        {addExpanded && (
          <div className="add-project">
            <form
              className="add-project__form"
              onSubmit={async (e) => {
                e.preventDefault();
                if (!repoPath.trim()) return;
                setAdding(true);
                setAddError(null);
                try {
                  const project = await createProjectFromRepo(repoPath.trim());
                  setRepoPath('');
                  setAddExpanded(false);
                  navigate(`/projects/${project.id}`);
                } catch (err) {
                  setAddError(err.message || 'Failed to create project');
                } finally {
                  setAdding(false);
                }
              }}
            >
              <input
                className="add-project__input"
                type="text"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="/path/to/repo"
                autoFocus
              />
              <button
                className="sync-btn"
                type="submit"
                disabled={adding || !repoPath.trim()}
              >
                {adding ? '$ creating...' : '$ create'}
              </button>
            </form>
            {addError && <div className="add-project__error">{addError}</div>}
          </div>
        )}
        <div className="project-cards">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      </div>

      <div>
        <div className="dashboard__section-title">Time &amp; Tokens</div>
        <TimeTokens />
        <TokenAudit />
      </div>

      <div>
        <div className="dashboard__section-title">Agents</div>
        <AgentList />
      </div>

    </div>
  );
}

export default DashboardPage;
