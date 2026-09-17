// Path: src/pages/DocsPage.jsx
// File: DocsPage.jsx
// Created: 2026-03-29
// Purpose: Displays project documentation files with expandable cards. When the project IS the
//          repo this dashboard runs from (project.runs_own_tests, a resolved-path comparison),
//          it has no separate docs and the page points at the system docs view instead.
// Caller: App.jsx (route: /projects/:id/docs)
// Callees: react (useState, useEffect), react-router-dom (useParams, Link), useStore, api/docs (getProjectDocs)
// Data In: Route param (id), project from Zustand store, docs from API
// Data Out: Default export DocsPage component
// Last Modified: 2026-09-17 (DWB-574: branch on runs_own_tests instead of a hardcoded
//          prefix === 'DWB', which took the wrong branch forever on any clone)

import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import { getProjectDocs } from '../api/docs';

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

function DocsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);

  // DWB-574: "are we looking at the project whose repo this dashboard is
  // running from" is a path question, and the API already answers it. This was
  // `project?.prefix === 'DWB'`, which is true here only because the prefix
  // happens to be DWB: on any clone that named its project anything else, the
  // comparison silently stopped matching and this page took the wrong branch
  // forever. runs_own_tests (backend/app/config/server_repo.py) resolves both
  // paths and compares them, so it holds whatever the project is called. The
  // name is test-flavoured because DWB-571 needed the same answer first; the
  // underlying question is "is this project this server's own repo", which is
  // exactly what this branch asks.
  const isOwnRepo = Boolean(project?.runs_own_tests);

  useEffect(() => {
    if (!id || isOwnRepo) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getProjectDocs(id)
      .then((data) => {
        if (!cancelled) setDocs(data.filter((d) => d.name !== 'INITIAL.md'));
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [id, isOwnRepo]);

  if (!project) {
    return <div className="empty-state">Project not found</div>;
  }

  if (isOwnRepo) {
    return (
      <div>
        <div className="page-title">{project.prefix} - Docs</div>
        <div className="docs-redirect">
          {/* States the rule, not a project name: this sentence has to stay
              true on a clone that calls the project something else. */}
          This project is the repo the dashboard itself runs from, so its docs
          are the system docs. View them under{' '}
          <Link to="/docs" className="docs-redirect__link">Overview, system_docs</Link>.
        </div>
      </div>
    );
  }

  if (loading) {
    return <div className="empty-state">Loading docs...</div>;
  }

  const existing = docs.filter((d) => d.exists);
  const missing = docs.filter((d) => !d.exists);

  return (
    <div>
      <div className="page-title">
        {project.prefix} - Docs
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
