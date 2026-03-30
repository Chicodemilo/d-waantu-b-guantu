// Path: src/components/epics/EpicList.jsx
// File: EpicList.jsx
// Created: 2026-03-29
// Purpose: Renders expandable list of epics with progress bars and nested sprint breakdowns
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect), react-router-dom (Link), useStore, services/tracking, utils/format, StatusBadge, AsciiProgressBar, common.css
// Data In: projectId prop
// Data Out: default export EpicList component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTime, formatTokens } from '../../utils/format';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';
import '../../styles/common.css';

function EpicList({ projectId }) {
  const epics = useStore((s) => s.getEpicsByProject(projectId));
  const sprints = useStore((s) => s.sprints);
  const tickets = useStore((s) => s.tickets);
  const [expanded, setExpanded] = useState({});
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTrackingSummary(projectId)
      .then((data) => { if (!cancelled) setSummary(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [projectId]);

  const toggleExpand = (epicId) => {
    setExpanded((prev) => ({ ...prev, [epicId]: !prev[epicId] }));
  };

  // Build sprint tracking lookup from summary
  const sprintTrackingMap = {};
  if (summary) {
    for (const s of summary.per_sprint || []) {
      sprintTrackingMap[s.sprint_id] = s;
    }
  }

  return (
    <div>
      {epics.map((epic) => {
        const epicSprints = sprints.filter((s) => s.epic_id === epic.id);
        const epicSprintIds = new Set(epicSprints.map((s) => s.id));
        const epicTickets = tickets.filter((t) => epicSprintIds.has(t.sprint_id));
        const done = epicTickets.filter((t) => t.status === 'done').length;

        // Sum tracking data for all sprints in this epic
        let epicTime = 0;
        let epicTokens = 0;
        for (const sid of epicSprintIds) {
          const st = sprintTrackingMap[sid];
          if (st) {
            epicTime += st.time || 0;
            epicTokens += st.tokens || 0;
          }
        }

        const isExpanded = expanded[epic.id];

        return (
          <div key={epic.id} className="epic-card">
            <Link
              to={`/projects/${projectId}/epics/${epic.id}`}
              className="epic-card__link"
            >
              <div className="epic-card__header">
                <span className="epic-card__name">{epic.name}</span>
                <StatusBadge status={epic.status} />
              </div>
              {epic.description && (
                <div className="epic-card__desc">{epic.description}</div>
              )}
              <div className="epic-card__progress">
                <AsciiProgressBar value={done} max={epicTickets.length || 1} width={20} />
                <span className="epic-card__progress-label">
                  {done}/{epicTickets.length} done &middot; {formatTime(epicTime)} &middot; {formatTokens(epicTokens)} tokens
                </span>
              </div>
            </Link>
            {epicSprints.length > 0 && (
              <div className="epic-card__sprints">
                <button
                  className="epic-card__sprints-toggle"
                  onClick={() => toggleExpand(epic.id)}
                >
                  <span className={`epic-card__caret${isExpanded ? ' epic-card__caret--open' : ''}`}>&gt;</span>
                  {epicSprints.length} sprint{epicSprints.length !== 1 ? 's' : ''}
                </button>
                {isExpanded && (
                  <ul className="epic-card__sprint-list">
                    {epicSprints.map((sprint) => {
                      const sprintTickets = tickets.filter((t) => t.sprint_id === sprint.id);
                      const sprintDone = sprintTickets.filter((t) => t.status === 'done').length;
                      return (
                        <li key={sprint.id} className="epic-card__sprint-item">
                          <Link
                            to={`/projects/${projectId}/sprints/${sprint.id}`}
                            className="epic-card__sprint-link"
                          >
                            S{sprint.sprint_number}: {sprint.name}
                          </Link>
                          <AsciiProgressBar value={sprintDone} max={sprintTickets.length || 1} width={12} />
                          <span className="epic-card__sprint-progress">
                            {sprintDone}/{sprintTickets.length} done
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </div>
        );
      })}
      {epics.length === 0 && (
        <div className="empty-state">No epics found</div>
      )}
    </div>
  );
}

export default EpicList;
