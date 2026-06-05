// Path: src/pages/JiraRollupPage.jsx
// File: JiraRollupPage.jsx
// Created: 2026-05-27
// Purpose: Project-level rollup of linked DWB tickets grouped by their Jira Epic
// Caller: App.jsx (route: /projects/:id/jira-rollup)
// Callees: ../store/useStore, ../api/jira
// Data In: Route param :id
// Data Out: Default export JiraRollupPage component
// Last Modified: 2026-05-27

import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { getJiraConfig, getJiraRollup, syncFromJira } from '../api/jira';
import '../styles/jira.css';

function JiraRollupPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const jiraConfig = useStore((s) => s.jiraConfig);
  const setJiraConfig = useStore((s) => s.setJiraConfig);

  const [rollup, setRollup] = useState(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (jiraConfig !== null) return;
    getJiraConfig().then(setJiraConfig).catch(() => setJiraConfig({ configured: false }));
  }, [jiraConfig, setJiraConfig]);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getJiraRollup(id);
      setRollup(data);
    } catch (e) {
      setError(e.message || 'Failed to load rollup');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!project?.jira_project_key || !jiraConfig?.configured) return;
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.jira_project_key, jiraConfig?.configured]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await syncFromJira(Number(id));
      setSyncResult(result);
      await refresh();
    } catch (e) {
      setError(e.message || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  if (!project) {
    return <div className="empty-state">Project not found</div>;
  }
  if (jiraConfig === null) {
    return <div className="empty-state">Loading Jira config…</div>;
  }
  if (!jiraConfig.configured) {
    return (
      <div className="jira-page">
        <div className="page-title">Jira Rollup</div>
        <div className="empty-state">
          Jira is not configured on this backend. Set <code>JIRA_BASE_URL</code>,{' '}
          <code>JIRA_EMAIL</code>, <code>JIRA_API_TOKEN</code> in <code>.env</code> and restart.
        </div>
      </div>
    );
  }
  if (!project.jira_project_key) {
    return (
      <div className="jira-page">
        <div className="page-title">Jira Rollup</div>
        <div className="empty-state">
          This project is not linked to a Jira project. Enable Jira from the{' '}
          <Link to={`/projects/${id}`}>project tools panel</Link>.
        </div>
      </div>
    );
  }

  return (
    <div className="jira-page">
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; Back to project</Link>
        <span style={{ marginLeft: '16px' }}>
          {project.prefix} Jira Rollup — {project.jira_project_key}
        </span>
      </div>

      <div className="jira-toolbar">
        <div>
          <Link to={`/projects/${id}/jira`}>$ open Jira browser</Link>
        </div>
        <div className="jira-toolbar__tabs">
          <button className="sync-btn" onClick={refresh} disabled={loading}>
            {loading ? '$ refreshing…' : '$ refresh'}
          </button>
          <button className="sync-btn" onClick={handleSync} disabled={syncing}>
            {syncing ? '$ syncing…' : '$ sync from Jira'}
          </button>
        </div>
      </div>

      {syncResult && (
        <div className="jira-sync-result">
          Synced {syncResult.synced} ticket{syncResult.synced !== 1 ? 's' : ''}
          {' · '}
          <strong>{syncResult.changed}</strong> updated
          {syncResult.unmapped?.length > 0 && (
            <> · {syncResult.unmapped.length} unmapped status{syncResult.unmapped.length !== 1 ? 'es' : ''}</>
          )}
          {syncResult.errors?.length > 0 && (
            <> · <span style={{ color: 'var(--red)' }}>{syncResult.errors.length} error{syncResult.errors.length !== 1 ? 's' : ''}</span></>
          )}
        </div>
      )}

      {error && <div className="jira-error">Error: {error}</div>}

      {rollup && rollup.epics.length === 0 && (
        <div className="empty-state">
          No linked tickets in this project. Link a DWB ticket to a Jira issue from the ticket detail page.
        </div>
      )}

      {rollup && rollup.epics.length > 0 && (
        <div className="jira-rollup">
          <div className="jira-rollup__row jira-rollup__row--header">
            <span>Epic</span>
            <span>Summary</span>
            <span className="jira-rollup__counts">Linked</span>
            <span className="jira-rollup__counts">Done</span>
            <span className="jira-rollup__counts">In Prog</span>
            <span className="jira-rollup__counts">In Review</span>
            <span className="jira-rollup__counts">To Do</span>
            <span className="jira-rollup__bar">Completion</span>
          </div>
          {rollup.epics.map((e, idx) => (
            <div key={e.epic_key || `noepic-${idx}`} className="jira-rollup__row">
              <span className="jira-rollup__epic">
                {e.epic_key ? (
                  <a
                    href={`${jiraConfig.base_url}/browse/${e.epic_key}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >{e.epic_key}</a>
                ) : (
                  <span className="jira-rollup__no-epic">(no epic)</span>
                )}
              </span>
              <span className="jira-rollup__summary" title={e.epic_summary}>{e.epic_summary || '—'}</span>
              <span className="jira-rollup__counts">{e.linked_count}</span>
              <span className="jira-rollup__counts">{e.done}</span>
              <span className="jira-rollup__counts">{e.in_progress}</span>
              <span className="jira-rollup__counts">{e.in_review}</span>
              <span className="jira-rollup__counts">{e.todo}</span>
              <span className="jira-rollup__bar">
                <span className="jira-rollup__bar-track">
                  <span
                    className="jira-rollup__bar-fill"
                    style={{ width: `${e.completion_pct}%` }}
                  />
                </span>
                <span className="jira-rollup__bar-pct">{e.completion_pct}%</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default JiraRollupPage;
