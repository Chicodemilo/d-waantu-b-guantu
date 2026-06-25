// Path: src/pages/SessionsPage.jsx
// File: SessionsPage.jsx
// Created: 2026-06-10
// Purpose: Primary DWB sessions page for a project. Phrase-help teaching block sits at the top (under the page heading, before the table) and explains how to open/close a session (regex phrases plus the /dwb-open and /dwb-close slash commands; idle sweeper auto-closes), with an inline `(info)` affordance that expands a longer description via <details>. The SessionsTable is the dominant primary content (every session, scannable). A small `view current session ->` link in the header points at /projects/:id/sessions/current for the live SessionPanel drill-down.
// Caller: App.jsx (route: /projects/:id/sessions)
// Callees: react-router-dom (useParams, Link), store/useStore, ../components/project/SessionsTable, ../styles/dashboard.css, ../styles/sessions.css
// Data In: Route param id (project id), project from store
// Data Out: Default export SessionsPage component
// Last Modified: 2026-06-25 (DWB-487: SessionsTable rendered with searchable fuzzy filter)

import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import SessionsTable from '../components/project/SessionsTable';
import '../styles/dashboard.css';
import '../styles/sessions.css';

function SessionsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));

  if (!project) {
    return <div className="empty-state">Project not found</div>;
  }

  return (
    <div className="dashboard" data-testid="sessions-page">
      <div className="dashboard__breadcrumb">
        <Link to={`/projects/${id}`}>{project.prefix}</Link>
        <span> / sessions</span>
      </div>

      <div className="sessions-page__title-row">
        <h1 className="dashboard__title">{project.name} — DWB Sessions</h1>
        <Link
          to={`/projects/${id}/sessions/current`}
          className="sessions-page__current-link"
          data-testid="current-session-link"
        >
          view current session -&gt;
        </Link>
      </div>

      <div className="sessions-page__phrase-help" data-testid="phrase-help">
        <div className="sessions-page__phrase-row">
          <span className="sessions-page__phrase-label">Open with:</span>
          <span className="sessions-page__phrase-list">
            "you are archie, read the playbook" or "open the session"
          </span>
        </div>
        <div className="sessions-page__phrase-row">
          <span className="sessions-page__phrase-label">Close with:</span>
          <span className="sessions-page__phrase-list">
            "shut it down for the night" or "write docs and exit"
          </span>
        </div>
        <div className="sessions-page__phrase-row">
          <span className="sessions-page__phrase-label">Or use:</span>
          <span className="sessions-page__phrase-list">
            /dwb-open and /dwb-close for a deterministic open or close
          </span>
        </div>
        <details className="sessions-page__phrase-info" data-testid="phrase-info">
          <summary className="sessions-page__phrase-info-trigger">(info)</summary>
          <div className="sessions-page__phrase-info-body">
            These are phrases designed to trigger the start and close of a DWB session.
            A regex layer matches them on the user's prompts directly. For a deterministic
            open or close, use the slash commands /dwb-open and /dwb-close. An idle sweeper
            auto-closes a session left open too long. Full catalogue:
            backend/app/config/session_phrases.py
          </div>
        </details>
      </div>

      <SessionsTable projectId={id} searchable />
    </div>
  );
}

export default SessionsPage;
