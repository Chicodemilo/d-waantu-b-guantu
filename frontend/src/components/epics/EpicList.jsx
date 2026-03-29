import { useState } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';
import '../../styles/common.css';

function formatTime(seconds) {
  if (!seconds || seconds === 0) return '\u2014';
  if (seconds < 60) return '< 1m';
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`;
}

function formatTokens(tokens) {
  if (!tokens || tokens === 0) return '\u2014';
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return String(tokens);
}

function EpicList({ projectId }) {
  const epics = useStore((s) => s.getEpicsByProject(projectId));
  const sprints = useStore((s) => s.sprints);
  const tickets = useStore((s) => s.tickets);
  const [expanded, setExpanded] = useState({});

  const toggleExpand = (epicId) => {
    setExpanded((prev) => ({ ...prev, [epicId]: !prev[epicId] }));
  };

  return (
    <div>
      {epics.map((epic) => {
        const epicSprints = sprints.filter((s) => s.epic_id === epic.id);
        const epicSprintIds = new Set(epicSprints.map((s) => s.id));
        const epicTickets = tickets.filter((t) => epicSprintIds.has(t.sprint_id));
        const done = epicTickets.filter((t) => t.status === 'done').length;
        const epicTime = epicTickets.reduce((sum, t) => sum + (t.time_spent_seconds || 0), 0);
        const epicTokens = epicTickets.reduce((sum, t) => sum + (t.tokens_used || 0), 0);
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
