// Path: src/pages/SystemDocsPage.jsx
// File: SystemDocsPage.jsx
// Created: 2026-03-29
// Purpose: Displays DWB system documentation from the repo root via GET /api/system/docs
// Caller: App.jsx (route: /docs)
// Callees: react (useState, useEffect), api/docs (getSystemDocs), styles/docs.css
// Data In: System docs from API
// Data Out: Default export SystemDocsPage component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { getSystemDocs } from '../api/docs';
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

function SystemDocsPage() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getSystemDocs()
      .then((data) => {
        if (!cancelled) setDocs(data.filter((d) => d.name !== 'INITIAL.md'));
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <div className="empty-state">Loading docs...</div>;
  }

  const existing = docs.filter((d) => d.exists);
  const missing = docs.filter((d) => !d.exists);

  return (
    <div>
      <div className="page-title">
        System Docs
        <span className="tooltip-trigger">
          ?
          <span className="tooltip-content">
            System docs are read live from the DWB repo root. Edit them at the shown path and they update here automatically.
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
          <div className="empty-state">No system documentation found</div>
        )}
      </div>
    </div>
  );
}

export default SystemDocsPage;
