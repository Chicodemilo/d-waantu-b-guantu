// Path: src/components/dashboard/ProjectCard.jsx
// File: ProjectCard.jsx
// Created: 2026-03-29
// Purpose: Dashboard card displaying a project summary with ticket stats, token usage, time spent, and progress bar
// Caller: DashboardPage.jsx
// Callees: react (useState, useEffect), react-router-dom (Link), useStore, services/tracking, utils/format, StatusBadge, AsciiProgressBar, dashboard.css
// Data In: props { project }; tickets from store; tracking summary from API
// Data Out: default export ProjectCard component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTime, formatTokens } from '../../utils/format';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';
import '../../styles/dashboard.css';

function ProjectCard({ project }) {
  const tickets = useStore((s) => s.getTicketsByProject(project.id));
  const done = tickets.filter((t) => t.status === 'done').length;
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTrackingSummary(project.id)
      .then((data) => { if (!cancelled) setSummary(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [project.id]);

  const totalTokens = summary ? (summary.project_total.tokens || 0) : 0;
  const totalTime = summary ? (summary.project_total.time || 0) : 0;

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
          <div className="project-card__stat-value">{formatTokens(totalTokens)}</div>
          <div className="project-card__stat-label">Tokens</div>
        </div>
        <div className="project-card__stat">
          <div className="project-card__stat-value">{formatTime(totalTime)}</div>
          <div className="project-card__stat-label">Time</div>
        </div>
      </div>
      <AsciiProgressBar value={done} max={tickets.length || 1} width={24} />
    </Link>
  );
}

export default ProjectCard;
