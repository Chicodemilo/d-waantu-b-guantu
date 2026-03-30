// Path: src/components/project/SprintProgress.jsx
// File: SprintProgress.jsx
// Created: 2026-03-29
// Purpose: Shows current/active sprint progress with ticket counts, tokens, time, and goal
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect), useStore, services/tracking, utils/format, StatusBadge, AsciiProgressBar
// Data In: projectId prop
// Data Out: default export SprintProgress component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTime, formatTokens } from '../../utils/format';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';

function SprintProgress({ projectId }) {
  const sprints = useStore((s) => s.getSprintsByProject(projectId));
  const tickets = useStore((s) => s.tickets);
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTrackingSummary(projectId)
      .then((data) => { if (!cancelled) setSummary(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [projectId]);

  const sorted = [...sprints].sort((a, b) => b.sprint_number - a.sprint_number);
  const activeSprint = sorted.find((s) => s.status === 'active') || sorted[0];
  if (!activeSprint) return null;

  const sprintTickets = tickets.filter((t) => t.sprint_id === activeSprint.id);
  const done = sprintTickets.filter((t) => t.status === 'done').length;
  const inProgress = sprintTickets.filter((t) => t.status === 'in_progress').length;

  const sprintTracking = summary
    ? (summary.per_sprint || []).find((s) => s.sprint_id === activeSprint.id)
    : null;
  const totalTokens = sprintTracking ? (sprintTracking.tokens || 0) : 0;
  const totalSeconds = sprintTracking ? (sprintTracking.time || 0) : 0;

  return (
    <div className="ascii-chart">
      <div className="ascii-chart__title">
        Current Sprint: S{activeSprint.sprint_number}: {activeSprint.name}
      </div>
      <div className="ascii-chart__row">
        <span className="ascii-chart__label">Status</span>
        <StatusBadge status={activeSprint.status} />
      </div>
      <div className="ascii-chart__row">
        <span className="ascii-chart__label">Progress</span>
        <AsciiProgressBar value={done} max={sprintTickets.length || 1} width={20} />
      </div>
      <div className="ascii-chart__row">
        <span className="ascii-chart__label">Tickets</span>
        <span className="ascii-chart__value">
          {done}/{sprintTickets.length} done, {inProgress} in progress
        </span>
      </div>
      <div className="ascii-chart__row">
        <span className="ascii-chart__label">Tokens</span>
        <span className="ascii-chart__value">{formatTokens(totalTokens)}</span>
      </div>
      <div className="ascii-chart__row">
        <span className="ascii-chart__label">Time</span>
        <span className="ascii-chart__value">{formatTime(totalSeconds)}</span>
      </div>
      <div className="ascii-chart__row">
        <span className="ascii-chart__label">Goal</span>
        <span className="ascii-chart__value">{activeSprint.goal}</span>
      </div>
    </div>
  );
}

export default SprintProgress;
