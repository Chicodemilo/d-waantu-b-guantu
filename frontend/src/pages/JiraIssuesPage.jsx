// Path: src/pages/JiraIssuesPage.jsx
// File: JiraIssuesPage.jsx
// Created: 2026-05-27
// Purpose: Jira proxy view — search issues, view sprint board, inspect issue detail
// Caller: App.jsx (route: /projects/:id/jira)
// Callees: ../store/useStore, ../api/jira, ../components/jira/*
// Data In: Route param :id (DWB project id)
// Data Out: Default export JiraIssuesPage component
// Last Modified: 2026-05-27

import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import {
  getJiraConfig,
  searchJiraIssues,
  listActiveSprints,
  listSprintIssues,
  clearJiraCache,
} from '../api/jira';
import JiraIssueList from '../components/jira/JiraIssueList';
import JiraSprintBoard from '../components/jira/JiraSprintBoard';
import JiraIssueDetail from '../components/jira/JiraIssueDetail';
import '../styles/jira.css';

function JiraIssuesPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const jiraConfig = useStore((s) => s.jiraConfig);
  const setJiraConfig = useStore((s) => s.setJiraConfig);

  const [view, setView] = useState('list'); // 'list' | 'board'
  const [jql, setJql] = useState('');
  const [issues, setIssues] = useState([]);
  const [sprints, setSprints] = useState([]);
  const [activeSprintId, setActiveSprintId] = useState(null);
  const [selectedKey, setSelectedKey] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const jiraProjectKey = project?.jira_project_key;
  const defaultJql = jiraProjectKey
    ? `project = ${jiraProjectKey} AND statusCategory != Done ORDER BY updated DESC`
    : '';

  // Probe config once.
  useEffect(() => {
    if (jiraConfig !== null) return;
    getJiraConfig()
      .then(setJiraConfig)
      .catch(() => setJiraConfig({ configured: false }));
  }, [jiraConfig, setJiraConfig]);

  // Seed JQL from project once.
  useEffect(() => {
    if (!jql && defaultJql) setJql(defaultJql);
  }, [defaultJql]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load sprints when board view opens (or project changes).
  useEffect(() => {
    if (view !== 'board' || !jiraProjectKey || !jiraConfig?.configured) return;
    setLoading(true);
    setError(null);
    listActiveSprints(jiraProjectKey)
      .then((data) => {
        setSprints(data);
        setActiveSprintId(data[0]?.id || null);
      })
      .catch((e) => setError(e.message || 'Failed to load sprints'))
      .finally(() => setLoading(false));
  }, [view, jiraProjectKey, jiraConfig?.configured]);

  // Load board issues when sprint changes.
  useEffect(() => {
    if (view !== 'board' || !activeSprintId) return;
    setLoading(true);
    listSprintIssues(activeSprintId)
      .then(setIssues)
      .catch((e) => setError(e.message || 'Failed to load sprint issues'))
      .finally(() => setLoading(false));
  }, [view, activeSprintId]);

  const runSearch = async (e) => {
    e?.preventDefault();
    if (!jql.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await searchJiraIssues(jql, 100);
      setIssues(data);
    } catch (err) {
      setError(err.message || 'Search failed');
      setIssues([]);
    } finally {
      setLoading(false);
    }
  };

  // Run an initial search when list view first opens with a default JQL.
  useEffect(() => {
    if (view === 'list' && jql && issues.length === 0 && jiraConfig?.configured && !error) {
      runSearch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, jiraConfig?.configured, jql]);

  const handleClearCache = async () => {
    try {
      await clearJiraCache();
      if (view === 'list') runSearch();
      else if (activeSprintId) {
        const data = await listSprintIssues(activeSprintId);
        setIssues(data);
      }
    } catch {
      // surfaced via next action's error handler
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
        <div className="page-title">Jira</div>
        <div className="empty-state">
          Jira is not configured on this backend. Set <code>JIRA_BASE_URL</code>,{' '}
          <code>JIRA_EMAIL</code>, and <code>JIRA_API_TOKEN</code> in <code>.env</code>{' '}
          and restart the API.
        </div>
      </div>
    );
  }

  if (!jiraProjectKey) {
    return (
      <div className="jira-page">
        <div className="page-title">Jira</div>
        <div className="empty-state">
          This project is not linked to a Jira project yet. Enable Jira from the{' '}
          <Link to={`/projects/${id}`}>project tools panel</Link>.
        </div>
      </div>
    );
  }

  const selectedIssue = issues.find((i) => i.key === selectedKey) || null;

  return (
    <div className="jira-page">
      <div className="page-title">
        {project.prefix} Jira — {jiraProjectKey}
      </div>

      <div className="jira-toolbar">
        <div className="jira-toolbar__tabs">
          <button
            className={`jira-tab${view === 'list' ? ' jira-tab--active' : ''}`}
            onClick={() => setView('list')}
          >List</button>
          <button
            className={`jira-tab${view === 'board' ? ' jira-tab--active' : ''}`}
            onClick={() => setView('board')}
          >Sprint Board</button>
        </div>
        <button className="sync-btn" onClick={handleClearCache} title="Drop the backend Jira cache and refetch">
          $ refresh
        </button>
      </div>

      {view === 'list' && (
        <form className="jira-search" onSubmit={runSearch}>
          <input
            className="jira-search__input"
            value={jql}
            onChange={(e) => setJql(e.target.value)}
            placeholder="JQL query (e.g. project = POR AND assignee = currentUser())"
            spellCheck={false}
          />
          <button className="sync-btn" type="submit" disabled={loading}>
            {loading ? '$ searching…' : '$ run'}
          </button>
        </form>
      )}

      {view === 'board' && sprints.length > 1 && (
        <div className="jira-sprint-picker">
          <label>Sprint:</label>
          <select
            value={activeSprintId || ''}
            onChange={(e) => setActiveSprintId(Number(e.target.value))}
          >
            {sprints.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
      )}

      {error && <div className="jira-error">Error: {error}</div>}

      <div className="jira-content">
        {view === 'list' && (
          <JiraIssueList
            issues={issues}
            loading={loading}
            baseUrl={jiraConfig.base_url}
            selectedKey={selectedKey}
            onSelect={setSelectedKey}
          />
        )}
        {view === 'board' && (
          <JiraSprintBoard
            issues={issues}
            loading={loading}
            baseUrl={jiraConfig.base_url}
            onSelect={setSelectedKey}
          />
        )}
        {selectedIssue && (
          <JiraIssueDetail
            issue={selectedIssue}
            baseUrl={jiraConfig.base_url}
            onClose={() => setSelectedKey(null)}
          />
        )}
      </div>
    </div>
  );
}

export default JiraIssuesPage;
