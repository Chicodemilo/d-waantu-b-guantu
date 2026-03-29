import useStore from '../../store/useStore';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';

function SprintProgress({ projectId }) {
  const sprints = useStore((s) => s.getSprintsByProject(projectId));
  const tickets = useStore((s) => s.tickets);

  const sorted = [...sprints].sort((a, b) => b.sprint_number - a.sprint_number);
  const activeSprint = sorted.find((s) => s.status === 'active') || sorted[0];
  if (!activeSprint) return null;

  const sprintTickets = tickets.filter((t) => t.sprint_id === activeSprint.id);
  const done = sprintTickets.filter((t) => t.status === 'done').length;
  const inProgress = sprintTickets.filter((t) => t.status === 'in_progress').length;
  const totalTokens = sprintTickets.reduce((sum, t) => sum + t.tokens_used, 0);
  const totalSeconds = sprintTickets.reduce((sum, t) => sum + (t.time_spent_seconds || 0), 0);

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
        <span className="ascii-chart__value">{totalTokens.toLocaleString()}</span>
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
