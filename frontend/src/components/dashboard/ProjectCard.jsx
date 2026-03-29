// Path: src/components/dashboard/ProjectCard.jsx
// File: ProjectCard.jsx
// Created: 2026-03-29
// Purpose: Dashboard card displaying a project summary with ticket stats, token usage, time spent, and progress bar
// Caller: DashboardPage.jsx
// Callees: react-router-dom (Link), useStore, StatusBadge, AsciiProgressBar, dashboard.css
// Data In: props { project }; tickets from store via getTicketsByProject
// Data Out: default export ProjectCard component
// Last Modified: 2026-03-29

import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';
import '../../styles/dashboard.css';

function ProjectCard({ project }) {
  const tickets = useStore((s) => s.getTicketsByProject(project.id));
  const done = tickets.filter((t) => t.status === 'done').length;
  const totalTokens = tickets.reduce((sum, t) => sum + t.tokens_used, 0);
  const totalSeconds = tickets.reduce((sum, t) => sum + (t.time_spent_seconds || 0), 0);

  const formatTime = (seconds) => {
    if (!seconds || seconds === 0) return '\u2014';
    if (seconds < 60) return '< 1m';
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    const rem = mins % 60;
    return rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`;
  };

  return (
    <Link to={`/projects/${project.id}`} className="project-card">
      <div className="project-card__header">
        <span className="project-card__prefix">{project.prefix}</span>
        <StatusBadge status={project.status} />
      </div>
      <div className="project-card__name">{project.name}</div>
      <div className="project-card__desc">{project.description}</div>
      <div className="project-card__stats">
        <div className="project-card__stat">
          <div className="project-card__stat-value">{tickets.length}</div>
          <div className="project-card__stat-label">Tickets</div>
        </div>
        <div className="project-card__stat">
          <div className="project-card__stat-value">{done}</div>
          <div className="project-card__stat-label">Done</div>
        </div>
        <div className="project-card__stat">
          <div className="project-card__stat-value">
            {(totalTokens / 1000).toFixed(1)}k
          </div>
          <div className="project-card__stat-label">Tokens</div>
        </div>
        <div className="project-card__stat">
          <div className="project-card__stat-value">{formatTime(totalSeconds)}</div>
          <div className="project-card__stat-label">Time</div>
        </div>
      </div>
      <AsciiProgressBar value={done} max={tickets.length || 1} width={24} />
    </Link>
  );
}

export default ProjectCard;
