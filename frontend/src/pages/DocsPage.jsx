// Path: src/pages/DocsPage.jsx
// File: DocsPage.jsx
// Created: 2026-03-29
// Purpose: Displays project documentation files with expandable cards; used for both project docs and system docs
// Caller: App.jsx (routes: /projects/:id/docs, /docs)
// Callees: react (useState, useEffect), react-router-dom (useParams), useStore, api/docs (getProjectDocs), styles/docs.css
// Data In: Route param (id) or systemProjectId prop, project from Zustand store, docs from API
// Data Out: Default export DocsPage component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import { getProjectDocs } from '../api/docs';
import '../styles/docs.css';

function DocCard({ doc }) {
  const [expanded, setExpanded] = useState(false);

  if (!doc.exists) {
    return (
      <div className="doc-card doc-card--missing">
        <div className="doc-card__header">
          <span className="doc-card__name doc-card__name--missing">{doc.name}</span>
          <span className="doc-card__badge">missing</span>
        </div>
        <div className="doc-card__path">{doc.path}</div>
      </div>
    );
  }

  return (
    <div className="doc-card">
      <button className="doc-card__header" onClick={() => setExpanded(!expanded)}>
        <span className={`doc-card__caret${expanded ? ' doc-card__caret--open' : ''}`}>&gt;</span>
        <span className="doc-card__name">{doc.name}</span>
      </button>
      <div className="doc-card__path">{doc.path}</div>
      {expanded && (
        <div className="doc-card__body">
          <pre className="doc-card__content">{doc.content}</pre>
        </div>
      )}
    </div>
  );
}

function DocsPage({ systemProjectId }) {
  const { id: routeId } = useParams();
  const projectId = systemProjectId || routeId;
  const project = useStore((s) => s.getProject(projectId));
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    getProjectDocs(projectId)
      .then((data) => {
        if (!cancelled) setDocs(data.filter((d) => d.name !== 'INITIAL.md'));
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (!projectId || !project) {
    return <div className="empty-state">{systemProjectId ? 'System project not found' : 'Project not found'}</div>;
  }

  if (loading) {
    return <div className="empty-state">Loading docs...</div>;
  }

  const existing = docs.filter((d) => d.exists);
  const missing = docs.filter((d) => !d.exists);
  const title = systemProjectId ? 'System Docs' : `${project.prefix} \u2014 Docs`;

  return (
    <div>
      <div className="page-title">
        {title}
        <span className="tooltip-trigger">
          ?
          <span className="tooltip-content">
            Project docs are read live from the repo. Edit them at the shown path and they update here automatically. Missing docs show the expected path where you can create them.
          </span>
        </span>
      </div>
      <div className="docs-list">
        {existing.map((doc) => (
          <DocCard key={doc.name} doc={doc} />
        ))}
        {missing.length > 0 && existing.length > 0 && (
          <div className="docs-list__divider" />
        )}
        {missing.map((doc) => (
          <DocCard key={doc.name} doc={doc} />
        ))}
        {docs.length === 0 && (
          <div className="empty-state">No documentation configured for this project</div>
        )}
      </div>
    </div>
  );
}

export default DocsPage;
