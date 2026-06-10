// Path: src/pages/SessionCurrentPage.jsx
// File: SessionCurrentPage.jsx
// Created: 2026-06-10
// Purpose: Thin host page for the SessionPanel live current-session view at /projects/:id/sessions/current. Moved off SessionsPage in DWB-349 after the user re-prioritized the sessions TABLE as the primary content; SessionPanel still has a home but is now a side trip rather than the dominant block.
// Caller: App.jsx (route: /projects/:id/sessions/current)
// Callees: react-router-dom (useParams, Link), store/useStore, ../components/project/SessionPanel, ../styles/dashboard.css, ../styles/sessions.css
// Data In: Route param id (project id), project from store
// Data Out: Default export SessionCurrentPage component
// Last Modified: 2026-06-10

import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import SessionPanel from '../components/project/SessionPanel';
import '../styles/dashboard.css';
import '../styles/sessions.css';

function SessionCurrentPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));

  if (!project) {
    return <div className="empty-state">Project not found</div>;
  }

  return (
    <div className="dashboard" data-testid="session-current-page">
      <div className="dashboard__breadcrumb">
        <Link to={`/projects/${id}`}>{project.prefix}</Link>
        <span> / </span>
        <Link to={`/projects/${id}/sessions`}>sessions</Link>
        <span> / current</span>
      </div>

      <h1 className="dashboard__title">Current Session: {project.name}</h1>
      <SessionPanel projectId={id} />
    </div>
  );
}

export default SessionCurrentPage;
