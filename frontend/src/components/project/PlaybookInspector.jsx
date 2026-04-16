// Path: src/components/project/PlaybookInspector.jsx
// File: PlaybookInspector.jsx
// Created: 2026-04-16
// Purpose: Split view of playbook files (3 generic playbooks + 3 project rules) with expandable content, tooltips, path, and date
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

  const playbooks = files.filter((f) => f.name.includes('playbook'));
  const projectRules = files.filter((f) => f.name.includes('project_rules'));

  if (files.length === 0) {
    return (
      <div className="playbook-inspector">
        <div className="empty-state">No playbook files configured</div>
      </div>
    );
  }

  return (
    <div className="playbook-inspector">
      {playbooks.length > 0 && (
        <div className="playbook-inspector__section">
          <div className="dashboard__section-title">
            Playbooks
            <span className="tooltip-trigger">
              ?
              <span className="tooltip-content">
                Generic operating procedures deployed from DWB.
                <ul className="tooltip-list">
                  <li>Overwritten on every deploy — do not put project-specific rules here</li>
                  <li>Covers: TL operations, PM operations, worker workflow</li>
                </ul>
              </span>
            </span>
          </div>
          {playbooks.map((file) => (
            <PlaybookFile key={file.name} file={file} />
          ))}
        </div>
      )}
      {projectRules.length > 0 && (
        <div className="playbook-inspector__section">
          <div className="dashboard__section-title">
            Project Rules
            <span className="tooltip-trigger">
              ?
              <span className="tooltip-content">
                Project-specific rules that persist across deploys.
                <ul className="tooltip-list">
                  <li>Created blank on first deploy, never overwritten</li>
                  <li>Each agent reads their project rules file on startup</li>
                </ul>
              </span>
            </span>
          </div>
          {projectRules.map((file) => (
            <PlaybookFile key={file.name} file={file} />
          ))}
        </div>
      )}
    </div>
  );
}

export default PlaybookInspector;
