// Path: src/components/project/PlaybookInspector.jsx
// File: PlaybookInspector.jsx
// Created: 2026-04-16
// Purpose: Collapsible panel listing all 6 playbook files with expandable content, path, and last-modified date
// Caller: ProjectAgentsPage.jsx
// Callees: react (useState, useEffect), api/projects (getPlaybookFiles), styles/docs.css
// Data In: props { projectId }
// Data Out: Default export PlaybookInspector component
// Last Modified: 2026-04-16

import { useState, useEffect } from 'react';
import { getPlaybookFiles } from '../../api/projects';
import '../../styles/docs.css';

function PlaybookFile({ file }) {
  const [expanded, setExpanded] = useState(false);

  const formatDate = (dateStr) => {
    if (!dateStr) return null;
    return new Date(dateStr).toLocaleDateString();
  };

  if (!file.exists) {
    return (
      <div className="playbook-file">
        <div className="playbook-file__header playbook-file__header--static">
          <span className="playbook-file__name playbook-file__name--missing">{file.name}</span>
          <span className="playbook-file__badge">missing</span>
          <span className="playbook-file__meta">
            <span className="playbook-file__path">{file.path}</span>
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="playbook-file">
      <button
        className="playbook-file__header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`playbook-file__caret${expanded ? ' playbook-file__caret--open' : ''}`}>&gt;</span>
        <span className="playbook-file__name">{file.name}</span>
        <span className="playbook-file__meta">
          <span className="playbook-file__path">{file.path}</span>
          {file.last_modified && (
            <span className="playbook-file__date">{formatDate(file.last_modified)}</span>
          )}
        </span>
      </button>
      {expanded && (
        <div className="playbook-file__body">
          <pre className="playbook-file__content">{file.content}</pre>
        </div>
      )}
    </div>
  );
}

function PlaybookInspector({ projectId }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    getPlaybookFiles(projectId)
      .then((data) => {
        if (!cancelled) setFiles(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) {
    return (
      <div className="playbook-inspector">
        <span className="playbook-inspector__loading">&gt; loading playbooks...</span>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="playbook-inspector">
        <div className="empty-state">No playbook files configured</div>
      </div>
    );
  }

  return (
    <div className="playbook-inspector">
      {files.map((file) => (
        <PlaybookFile key={file.name} file={file} />
      ))}
    </div>
  );
}

export default PlaybookInspector;
