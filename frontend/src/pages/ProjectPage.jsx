// Path: src/pages/ProjectPage.jsx
// File: ProjectPage.jsx
// Created: 2026-03-29
// Purpose: Project detail page with tools (deploy, scan, archive, delete), sprint gates, doc gates (incl. force_team_md), TEAM.md panel, alerts, sprint progress, overhead, velocity, and epics
// Caller: App.jsx (route: /projects/:id)
// Callees: react, react-router-dom, ../store/useStore, ../components/project/ProjectHeader, ../api/projects, ../api/alerts, ../components/project/SprintProgress, ../components/project/OverheadTracker, ../components/project/ActivityFeed, ../components/project/TeamMdPanel, ../components/sprints/SprintVelocity, ../components/epics/EpicList, ../components/common/AlertBanner, ../styles/dashboard.css
// Data In: Route param (id), project and alerts from Zustand store
// Data Out: Default export ProjectPage component
// Last Modified: 2026-04-16

import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import useStore from '../store/useStore';
import ProjectHeader from '../components/project/ProjectHeader';
import { deployPlaybooks, updateProject, deleteProject, disableJira } from '../api/projects';
import { dismissAllAlerts, getAlerts } from '../api/alerts';
import SprintProgress from '../components/project/SprintProgress';
import OverheadTracker from '../components/project/OverheadTracker';
import TimeTokens from '../components/dashboard/TimeTokens';
import SprintVelocity from '../components/sprints/SprintVelocity';
import EpicList from '../components/epics/EpicList';
import AlertBanner from '../components/common/AlertBanner';
import ActivityFeed from '../components/project/ActivityFeed';
import LiveSessions from '../components/project/LiveSessions';
import TeamMdPanel from '../components/project/TeamMdPanel';

import '../styles/dashboard.css';

function ProjectPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const project = useStore((s) => s.getProject(id));
  const setAlerts = useStore((s) => s.setAlerts);
  const tickets = useStore((s) => s.getTicketsByProject(id));
  const jiraLinkedCount = tickets.filter((t) => t.jira_issue_key).length;
  const alerts = useStore((s) => s.alerts).filter(
    (a) => a.project_id === Number(id) && a.status === 'open'
  );

  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState(null);
  const [archiving, setArchiving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [toggling, setToggling] = useState({});
  const [dismissing, setDismissing] = useState(false);
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [jiraKeyInput, setJiraKeyInput] = useState(''); // unused but kept for state cleanup
  const [jiraSaving, setJiraSaving] = useState(false);
  const [jiraDisabling, setJiraDisabling] = useState(false);
  const [jiraConfirmDisable, setJiraConfirmDisable] = useState(false);

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

  const handleArchiveToggle = async () => {
    setArchiving(true);
    const newStatus = project.status === 'archived' ? 'active' : 'archived';
    try {
      await updateProject(id, { status: newStatus });
      if (newStatus === 'archived') {
        navigate('/');
      } else {
        navigate(`/projects/${id}`);
        setArchiving(false);
      }
    } catch {
      setArchiving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteProject(id);
      navigate('/');
    } catch {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const handleDismissAll = async () => {
    setDismissing(true);
    try {
      await dismissAllAlerts();
      const fresh = await getAlerts();
      setAlerts(fresh);
    } catch {
      // next poll will refresh
    } finally {
      setDismissing(false);
    }
  };

  const handleJiraEnable = async () => {
    setJiraSaving(true);
    try {
      await updateProject(id, {
        jira_project_key: project.prefix,
        jira_base_url: 'https://roadvantage.atlassian.net',
      });
    } catch {
      // next poll will refresh
    } finally {
      setJiraSaving(false);
    }
  };

  const handleJiraDisable = async () => {
    setJiraDisabling(true);
    try {
      await disableJira(id);
      setJiraConfirmDisable(false);
      setJiraKeyInput('');
    } catch {
      // next poll will refresh
    } finally {
      setJiraDisabling(false);
    }
  };

  const handleToggleGate = async (field) => {
    setToggling((prev) => ({ ...prev, [field]: true }));
    try {
      await updateProject(id, { [field]: !project[field] });
    } catch {
      // next poll will refresh
    } finally {
      setToggling((prev) => ({ ...prev, [field]: false }));
    }
  };

  if (!project) {
    return <div className="empty-state">Project not found</div>;
  }

  return (
    <div className="dashboard">
      <ProjectHeader project={project} />

      <div className="project-tools">
        <button
          className="project-tools__toggle"
          onClick={() => setToolsExpanded(!toolsExpanded)}
        >
          <span className={`project-tools__caret${toolsExpanded ? ' project-tools__caret--open' : ''}`}>&gt;</span>
          Tools
        </button>

          <div className={`project-tools__body${toolsExpanded ? ' project-tools__body--open' : ''}`}>
            {project.repo_path && (
              <div className="project-tools__group">
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
                    Copies TL and PM playbooks into this project's .claude/ directory so agents can read them.
                  </span>
                </span>
                {deployResult === 'done' && <span className="sync-btn__status">{'\u2713'} deployed</span>}
                {deployResult === 'error' && <span className="sync-btn__status" style={{ color: 'var(--red)' }}>deploy failed</span>}
              </div>
            )}

            <div className="project-tools__group">
              <button
                className="sync-btn"
                onClick={handleArchiveToggle}
                disabled={archiving}
              >
                {archiving
                  ? (project.status === 'archived' ? '$ unarchiving...' : '$ archiving...')
                  : (project.status === 'archived' ? '$ unarchive' : '$ archive project')}
              </button>
              {!confirmDelete ? (
                <button
                  className="sync-btn sync-btn--danger"
                  onClick={() => setConfirmDelete(true)}
                >
                  $ delete project
                </button>
              ) : (
                <span className="project-actions__confirm">
                  <span className="project-actions__confirm-text">are you sure? this deletes everything.</span>
                  <button
                    className="sync-btn sync-btn--danger"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? '$ deleting...' : '$ yes, delete'}
                  </button>
                  <button
                    className="sync-btn"
                    onClick={() => setConfirmDelete(false)}
                  >
                    $ cancel
                  </button>
                </span>
              )}
            </div>

            <div className="project-tools__group">
              <span className="project-gates__label">
                Sprint Gates
                <span className="tooltip-trigger">
                  ?
                  <span className="tooltip-content">
                    When enabled, these gates must pass before a sprint can be closed.
                    <ul className="tooltip-list">
                      <li><strong>Force Headers</strong> — require code headers on all files</li>
                      <li><strong>Force Coverage</strong> — new endpoints must have test files</li>
                      <li><strong>Force Tests</strong> — test suite must run before sprint close</li>
                    </ul>
                  </span>
                </span>
              </span>
              {[
                { field: 'force_headers', label: 'Force Headers' },
                { field: 'force_test_coverage', label: 'Force Coverage' },
                { field: 'force_test_run', label: 'Force Tests' },
              ].map(({ field, label }) => (
                <button
                  key={field}
                  className={`project-gate__toggle${project[field] ? ' project-gate__toggle--on' : ''}`}
                  onClick={() => handleToggleGate(field)}
                  disabled={toggling[field]}
                >
                  {label} [{project[field] ? 'ON' : 'OFF'}]
                </button>
              ))}
            </div>

            <div className="project-tools__group">
              <span className="project-gates__label">
                Doc Gates
                <span className="tooltip-trigger">
                  ?
                  <span className="tooltip-content">
                    When enabled, these documents must exist before work can proceed.
                    <ul className="tooltip-list">
                      <li><strong>Force INITIAL.md</strong> — require requirements and phases document</li>
                      <li><strong>Force ARCHITECTURE.md</strong> — require system design document</li>
                      <li><strong>Force TEAM.md</strong> — require team roster and agent playbooks</li>
                    </ul>
                  </span>
                </span>
              </span>
              {[
                { field: 'force_initial_md', label: 'Force INITIAL.md' },
                { field: 'force_architecture_md', label: 'Force ARCHITECTURE.md' },
                { field: 'force_team_md', label: 'Force TEAM.md' },
              ].map(({ field, label }) => (
                <button
                  key={field}
                  className={`project-gate__toggle${project[field] ? ' project-gate__toggle--on' : ''}`}
                  onClick={() => handleToggleGate(field)}
                  disabled={toggling[field]}
                >
                  {label} [{project[field] ? 'ON' : 'OFF'}]
                </button>
              ))}
            </div>

            <div className="project-tools__group">
              <span className="project-gates__label">
                Jira Integration
                <span className="tooltip-trigger">
                  ?
                  <span className="tooltip-content">
                    Links this project to a Jira project for ticket tracking. Disabling removes all Jira issue links from tickets in this project. Your Jira data is never modified.
                  </span>
                </span>
              </span>
              {project.jira_project_key ? (
                <>
                  <span className="jira-key-display">{project.jira_project_key}</span>
                  {!jiraConfirmDisable ? (
                    <button
                      className="sync-btn sync-btn--danger"
                      onClick={() => setJiraConfirmDisable(true)}
                    >
                      $ disable jira
                    </button>
                  ) : (
                    <span className="project-actions__confirm">
                      <span className="project-actions__confirm-text">
                        This will remove Jira links from {jiraLinkedCount} ticket{jiraLinkedCount !== 1 ? 's' : ''}. Jira issues are not affected. Continue?
                      </span>
                      <button
                        className="sync-btn sync-btn--danger"
                        onClick={handleJiraDisable}
                        disabled={jiraDisabling}
                      >
                        {jiraDisabling ? '$ disabling...' : '$ yes, disable'}
                      </button>
                      <button
                        className="sync-btn"
                        onClick={() => setJiraConfirmDisable(false)}
                      >
                        $ cancel
                      </button>
                    </span>
                  )}
                </>
              ) : (
                <button
                  className="sync-btn"
                  onClick={handleJiraEnable}
                  disabled={jiraSaving}
                >
                  {jiraSaving ? '$ enabling...' : '$ enable jira'}
                </button>
              )}
            </div>
          </div>
      </div>

      {project.force_team_md && (
        <div>
          <div className="dashboard__section-title">Team Roster</div>
          <TeamMdPanel projectId={id} />
        </div>
      )}

      <div>
        <div className="dashboard__section-title">Live Sessions</div>
        <LiveSessions projectId={id} />
      </div>

      {alerts.length > 0 && (
        <div>
          <div className="dashboard__section-title">
            Alerts
            <span className="tooltip-trigger">?<span className="tooltip-content"><strong>Alert severity:</strong><ul className="tooltip-list"><li><strong>Blue</strong> — info (heads up)</li><li><strong>Yellow</strong> — warning (needs attention)</li><li><strong>Red</strong> — critical (urgent action required)</li></ul></span></span>
            <button
              className="sync-btn"
              onClick={handleDismissAll}
              disabled={dismissing}
              style={{ marginLeft: '16px' }}
            >
              {dismissing ? '$ dismissing...' : '$ dismiss all'}
            </button>
          </div>
          <div className="alerts-container">
            {[...alerts].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)).map((alert) => (
              <AlertBanner key={alert.id} alert={alert} />
            ))}
          </div>
        </div>
      )}

      <div className="project-sprint-row">
        <div className="project-sprint-row__left">
          <div className="dashboard__section-title">Current Sprint</div>
          <SprintProgress projectId={id} />
        </div>
        <div className="project-sprint-row__right">
          <div className="dashboard__section-title">Recent Activity</div>
          <ActivityFeed projectId={id} />
        </div>
      </div>

      <div>
        <div className="dashboard__section-title">Time &amp; Tokens</div>
        <TimeTokens projectId={id} />
      </div>

      <div>
        <div className="dashboard__section-title">Velocity</div>
        <SprintVelocity projectId={id} />
      </div>

      <div>
        <div className="dashboard__section-title">Epics</div>
        <div className="epic-list-scroll">
          <EpicList projectId={id} />
        </div>
      </div>

      <div>
        <div className="dashboard__section-title">
          <Link to={`/projects/${id}/tickets`}>View All Tickets &rarr;</Link>
        </div>
      </div>

    </div>
  );
}

export default ProjectPage;
