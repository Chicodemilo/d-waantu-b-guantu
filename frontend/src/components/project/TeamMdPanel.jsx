// Path: src/components/project/TeamMdPanel.jsx
// File: TeamMdPanel.jsx
// Created: 2026-04-16
// Purpose: Collapsible read-only panel displaying TEAM.md content from project docs endpoint
// Caller: ProjectAgentsPage.jsx
// Callees: react (useState, useEffect), api/docs (getProjectDocs), styles/docs.css
// Data In: props { projectId }
// Data Out: Default export TeamMdPanel component
// Last Modified: 2026-04-16

import { useState, useEffect } from 'react';
import { getProjectDocs } from '../../api/docs';
import '../../styles/docs.css';

function TeamMdPanel({ projectId }) {
  const [expanded, setExpanded] = useState(false);
  const [teamDoc, setTeamDoc] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    getProjectDocs(projectId)
      .then((docs) => {
        if (cancelled) return;
        const team = docs.find((d) => d.name === 'TEAM.md');
        setTeamDoc(team || null);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) {
    return (
      <div className="team-md-panel">
        <span className="team-md-panel__loading">&gt; loading TEAM.md...</span>
      </div>
    );
  }

  if (!teamDoc) {
    return null;
  }

  if (!teamDoc.exists) {
    return (
      <div className="team-md-panel">
        <div className="team-md-panel__header">
          <span className="team-md-panel__name team-md-panel__name--missing">TEAM.md</span>
          <span className="team-md-panel__badge">missing</span>
        </div>
        <div className="team-md-panel__path">{teamDoc.path}</div>
      </div>
    );
  }

  return (
    <div className="team-md-panel">
      <button
        className="team-md-panel__header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`team-md-panel__caret${expanded ? ' team-md-panel__caret--open' : ''}`}>&gt;</span>
        <span className="team-md-panel__name">TEAM.md</span>
      </button>
      {expanded && (
        <div className="team-md-panel__body">
          <pre className="team-md-panel__content">{teamDoc.content}</pre>
        </div>
      )}
    </div>
  );
}

export default TeamMdPanel;
