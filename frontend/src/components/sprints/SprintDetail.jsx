// Path: src/components/sprints/SprintDetail.jsx
// File: SprintDetail.jsx
// Created: 2026-03-29
// Purpose: Displays sprint details with status, dates, progress bar, token/time stats, and ticket list
// Caller: SprintPage.jsx
// Callees: react-router-dom (Link), useStore, StatusBadge, AsciiProgressBar, common.css, tickets.css
// Data In: sprintId and projectId props
// Data Out: default export SprintDetail component
// Last Modified: 2026-03-29

import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { formatTime } from '../../utils/format';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';
import '../../styles/common.css';
import '../../styles/tickets.css';

function SprintDetail({ sprintId, projectId }) {
  const sprint = useStore((s) => s.getSprint(sprintId));
  const tickets = useStore((s) => s.getTicketsBySprint(sprintId));
  const agents = useStore((s) => s.agents);

  if (!sprint) return <div className="empty-state">Sprint not found</div>;

  const done = tickets.filter((t) => t.status === 'done').length;
  const totalTokens = tickets.reduce((sum, t) => sum + (t.tokens_used || 0), 0);
  const totalSeconds = tickets.reduce((sum, t) => sum + (t.time_spent_seconds || 0), 0);

  const getAgentName = (agentId) => {
    if (!agentId) return 'unassigned';
    const agent = agents.find((a) => a.id === agentId);
    return agent ? agent.name : 'unknown';
  };

  return (
    <div>
      <div className="sprint-detail__header">
        <div className="sprint-detail__name">S{sprint.sprint_number}: {sprint.name}</div>
        <div className="sprint-detail__goal">{sprint.goal}</div>
        <div className="sprint-detail__meta">
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Status:</span>
            <StatusBadge status={sprint.status} />
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Dates:</span>
            <span className="ticket-detail__meta-value">
              {sprint.start_date} &rarr; {sprint.end_date}
            </span>
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Progress:</span>
            <AsciiProgressBar value={done} max={tickets.length || 1} width={16} />
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Tokens:</span>
            <span className="ticket-detail__meta-value">{totalTokens.toLocaleString()}</span>
          </div>
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Time:</span>
            <span className="ticket-detail__meta-value">{formatTime(totalSeconds)}</span>
          </div>
        </div>
      </div>

      <div className="ticket-list">
        {tickets.map((ticket) => (
          <Link
            key={ticket.id}
            to={`/projects/${projectId}/tickets/${ticket.id}`}
            className="ticket-row"
          >
            <span className="ticket-row__key">{ticket.ticket_key}</span>
            <span className="ticket-row__title">{ticket.title}</span>
            <StatusBadge status={ticket.status} />
            <span className="ticket-row__type">{ticket.ticket_type}</span>
            <span className="ticket-row__agent">{getAgentName(ticket.assigned_agent_id)}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default SprintDetail;
