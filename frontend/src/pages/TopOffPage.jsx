// Path: src/pages/TopOffPage.jsx
// File: TopOffPage.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: The top-off landing page (DWB-590 emits a link to
//          /projects/:id/topoff on every fire; the page did not exist until
//          this ticket, so the link 404'd by design - a dead link over an
//          invented one). Shows the project's own topoff_enabled/interval
//          settings and each live hook session's prompt_count against that
//          interval, since there is no separate top-off event log to read -
//          the counter IS the mechanism (DWB-584/590), so it is the real
//          data this page has to show.
// Caller: App.jsx (route: /projects/:id/topoff)
// Callees: react (useState, useEffect), react-router-dom (useParams, Link),
//          store/useStore, api/hooks (getHookSessions)
// Data In: Route param (id), project from Zustand store, live hook sessions
// Data Out: Default export TopOffPage component
// Last Modified: 2026-09-30 (DWB-613)

import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { getHookSessions } from '../api/hooks';

function untilNext(promptCount, interval) {
  if (!interval || interval < 1) return null;
  const rem = promptCount % interval;
  return rem === 0 ? 0 : interval - rem;
}

function TopOffPage() {
  const { id } = useParams();
  const project = useStore((s) => s.projects).find((p) => p.id === Number(id));

  const [sessions, setSessions] = useState([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!project) return undefined;
    let cancelled = false;
    setLoaded(false);
    getHookSessions({ project_id: project.id, status: 'active' })
      .then((rows) => {
        if (!cancelled) setSessions(rows || []);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => { cancelled = true; };
  }, [project?.id]);

  if (!project) {
    return <div className="empty-state" data-testid="topoff-page">Project not found</div>;
  }

  const interval = project.topoff_interval;

  return (
    <div className="topoff-page" data-testid="topoff-page">
      <div className="page-title">
        <Link to={`/projects/${id}`}>&larr; {project.prefix}</Link>
        <span>Top-off</span>
      </div>

      <div className="topoff-page__note">
        Every {interval || '?'} prompts, the running session is told to self-check
        and its journal is searched for anything the current prompt might be
        repeating (DWB-612). The receipt in the transcript is one constant
        line; the four questions it stands for live in the worker playbook,
        not here.
      </div>

      <div className="topoff-page__status">
        <span className="topoff-page__stat">
          <span className="topoff-page__stat-label">enabled</span>
          <span className="topoff-page__stat-value">{project.topoff_enabled ? 'yes' : 'no'}</span>
        </span>
        <span className="topoff-page__stat">
          <span className="topoff-page__stat-label">interval</span>
          <span className="topoff-page__stat-value">{interval ?? '-'}</span>
        </span>
      </div>

      {!loaded ? (
        <div className="empty-state">Loading sessions...</div>
      ) : sessions.length === 0 ? (
        <div className="empty-state" data-testid="topoff-empty">no active sessions right now</div>
      ) : (
        <table className="data-table" data-testid="topoff-sessions">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Prompts so far</th>
              <th>Until next check</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => {
              const remaining = untilNext(s.prompt_count || 0, interval);
              return (
                <tr key={s.id}>
                  <td>{s.agent_name || `agent ${s.agent_id ?? '?'}`}</td>
                  <td>{s.prompt_count || 0}</td>
                  <td>
                    {!project.topoff_enabled
                      ? 'top-off is off'
                      : remaining == null
                        ? '-'
                        : remaining === 0
                          ? 'due now'
                          : remaining}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default TopOffPage;
