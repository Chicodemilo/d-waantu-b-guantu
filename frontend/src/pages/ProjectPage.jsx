// Path: src/pages/ProjectPage.jsx
// File: ProjectPage.jsx
// Created: 2026-03-29
// Purpose: Project detail page with tools (archive, delete), sprint gates (incl. force_consolidation), doc gates (incl. force_handoff_md), alerts, consolidation status panel, sprint progress, overhead, velocity, and epics
// Caller: App.jsx (route: /projects/:id)
// Callees: react, react-router-dom, ../store/useStore, ../components/project/ProjectHeader, ../api/projects, ../api/alerts, ../components/project/SprintProgress, ../components/project/ActivityFeed, ../components/project/LiveSessions, ../components/project/TokenBudget, ../components/project/ConsolidationStatus, ../components/sprints/SprintVelocity, ../components/epics/EpicList, ../components/common/AlertBanner, ../styles/dashboard.css
// Data In: Route param (id), project and alerts from Zustand store
// Data Out: Default export ProjectPage component
// Last Modified: 2026-06-04

import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import useStore from '../store/useStore';
import ProjectHeader from '../components/project/ProjectHeader';
import { updateProject, deleteProject, disableJira } from '../api/projects';
import { dismissAllAlerts, getAlerts, sendAlertsToTeam } from '../api/alerts';
import SprintProgress from '../components/project/SprintProgress';
import TimeTokens from '../components/dashboard/TimeTokens';
import SprintVelocity from '../components/sprints/SprintVelocity';
import EpicList from '../components/epics/EpicList';
import AlertBanner from '../components/common/AlertBanner';
import ActivityFeed from '../components/project/ActivityFeed';
import LiveSessions from '../components/project/LiveSessions';
import TokenBudget from '../components/project/TokenBudget';
import ConsolidationStatus from '../components/project/ConsolidationStatus';
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

  const [archiving, setArchiving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [toggling, setToggling] = useState({});
  const [dismissing, setDismissing] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState(null);
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [jiraKeyInput, setJiraKeyInput] = useState(''); // unused but kept for state cleanup
  const [jiraSaving, setJiraSaving] = useState(false);
  const [jiraDisabling, setJiraDisabling] = useState(false);
  const [jiraConfirmDisable, setJiraConfirmDisable] = useState(false);

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

  const handleSendToTeam = async () => {
    setSending(true);
    setSendResult(null);
    try {
      await sendAlertsToTeam(id);
      setSendResult('done');
    } catch {
      setSendResult('error');
    } finally {
      setSending(false);
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

            <div className="project-tools__section">
              <div className="project-tools__section-title">Project Actions</div>
              <div className="project-tools__row">
                <button
                  className="sync-btn"
                  onClick={handleArchiveToggle}
                  disabled={archiving}
                >
                  {archiving
                    ? (project.status === 'archived' ? '$ unarchiving...' : '$ archiving...')
                    : (project.status === 'archived' ? '$ unarchive' : '$ archive project')}
                </button>
                <span className="tooltip-trigger">
                  ?
                  <span className="tooltip-content">
                    Archives the project, hiding it from the active dashboard. All data is preserved. Unarchive to restore.
                  </span>
                </span>
              </div>
              <div className="project-tools__row">
                {!confirmDelete ? (
                  <>
                    <button
                      className="sync-btn sync-btn--danger"
                      onClick={() => setConfirmDelete(true)}
                    >
                      $ delete project
                    </button>
                    <span className="tooltip-trigger">
                      ?
                      <span className="tooltip-content">
                        Permanently deletes this project and ALL associated data: tickets, sprints, epics, agents, test results, alerts, tracking logs. This cannot be undone.
                      </span>
                    </span>
                  </>
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
            </div>

            <div className="project-tools__section">
              <div className="project-tools__section-title">Sprint Gates</div>
              {[
                { field: 'force_headers', label: 'Force Headers', tip: 'Require code headers on all source files. Not yet enforced automatically.' },
                { field: 'force_test_coverage', label: 'Force Coverage', tip: 'Every API router must have a corresponding test file before sprint close.' },
                { field: 'force_test_run', label: 'Force Tests', tip: 'At least one test run must be recorded during the sprint before it can be closed.' },
                { field: 'force_consolidation', label: 'Consolidation at sprint close', tip: 'Every project agent must acknowledge consolidation of their owned over-ceiling docs before the sprint can be closed. Agents POST to /api/agents/:id/consolidate-complete; gate status is shown in the Consolidation panel.' },
              ].map(({ field, label, tip }) => (
                <div key={field} className="project-tools__row">
                  <button
                    className={`project-gate__toggle${project[field] ? ' project-gate__toggle--on' : ''}`}
                    onClick={() => handleToggleGate(field)}
                    disabled={toggling[field]}
                  >
                    {label} [{project[field] ? 'ON' : 'OFF'}]
                  </button>
                  <span className="tooltip-trigger">
                    ?
                    <span className="tooltip-content">{tip}</span>
                  </span>
                </div>
              ))}
            </div>

            <div className="project-tools__section">
              <div className="project-tools__section-title">Doc Gates</div>
              {[
                { field: 'force_initial_md', label: 'Force INITIAL.md', file: 'INITIAL.md', tip: 'INITIAL.md must exist at the repo root. Contains project requirements, phases, and design decisions.' },
                { field: 'force_architecture_md', label: 'Force ARCHITECTURE.md', file: 'ARCHITECTURE.md', tip: 'ARCHITECTURE.md must exist at the repo root. Contains system design, data model, and API reference.' },
                { field: 'force_handoff_md', label: 'Force HANDOFF.md', file: 'HANDOFF.md', tip: 'HANDOFF.md must exist at the repo root. Session continuity notes — current state, decisions, gotchas.' },
              ].map(({ field, label, file, tip }) => (
                <div key={field} className="project-tools__row">
                  <button
                    className={`project-gate__toggle${project[field] ? ' project-gate__toggle--on' : ''}`}
                    onClick={() => handleToggleGate(field)}
                    disabled={toggling[field]}
                  >
                    {label} [{project[field] ? 'ON' : 'OFF'}]
                  </button>
                  <span className="tooltip-trigger">
                    ?
                    <span className="tooltip-content">{tip}</span>
                  </span>
                  {project.repo_path && (
                    <span className="project-tools__path">{project.repo_path}/{file}</span>
                  )}
                </div>
              ))}
            </div>

            <div className="project-tools__section">
              <div className="project-tools__section-title">Jira Integration</div>
              {project.jira_project_key ? (
                <>
                  <div className="project-tools__row">
                    <span className="jira-key-display">{project.jira_project_key}</span>
                  </div>
                  <div className="project-tools__row">
                    {!jiraConfirmDisable ? (
                      <>
                        <button
                          className="sync-btn sync-btn--danger"
                          onClick={() => setJiraConfirmDisable(true)}
                        >
                          $ disable jira
                        </button>
                        <span className="tooltip-trigger">
                          ?
                          <span className="tooltip-content">
                            Removes all Jira issue links from tickets in this project. Your Jira data is never modified. You can re-enable at any time.
                          </span>
                        </span>
                      </>
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
                  </div>
                </>
              ) : (
                <div className="project-tools__row">
                  <button
                    className="sync-btn"
                    onClick={handleJiraEnable}
                    disabled={jiraSaving}
                  >
                    {jiraSaving ? '$ enabling...' : '$ enable jira'}
                  </button>
                  <span className="tooltip-trigger">
                    ?
                    <span className="tooltip-content">
                      Links this project to a Jira project for ticket tracking. Uses the project prefix as the Jira project key.
                    </span>
                  </span>
                </div>
              )}
            </div>

          </div>
      </div>

      <TokenBudget projectId={id} />

      <ConsolidationStatus projectId={id} />

      <div>
        <div className="dashboard__section-title">Team Status</div>
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
            <button
              className="sync-btn"
              onClick={handleSendToTeam}
              disabled={sending}
              style={{ marginLeft: '8px' }}
            >
              {sending ? '$ sending...' : '$ send to team'}
            </button>
            {sendResult === 'done' && <span className="sync-btn__status">{'\u2713'} sent</span>}
            {sendResult === 'error' && <span className="sync-btn__status" style={{ color: 'var(--red)' }}>send failed</span>}
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
          {project.jira_project_key && (
            <>
              <Link to={`/projects/${id}/jira`} style={{ marginLeft: '24px' }}>
                View Jira Issues &rarr;
              </Link>
              <Link to={`/projects/${id}/jira-rollup`} style={{ marginLeft: '24px' }}>
                Jira Rollup &rarr;
              </Link>
            </>
          )}
        </div>
      </div>

    </div>
  );
}

export default ProjectPage;
