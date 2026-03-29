// Path: src/components/epics/EpicDetail.jsx
// File: EpicDetail.jsx
// Created: 2026-03-29
// Purpose: Displays epic details with progress bar, token/time stats, and linked ticket list
// Caller: EpicPage.jsx
// Callees: react-router-dom (Link), useStore, StatusBadge, AsciiProgressBar, common.css, tickets.css
// Data In: epicId and projectId props
// Data Out: default export EpicDetail component
// Last Modified: 2026-03-29

import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import StatusBadge from '../common/StatusBadge';
import AsciiProgressBar from '../common/AsciiProgressBar';
import '../../styles/common.css';
import '../../styles/tickets.css';

function EpicDetail({ epicId, projectId }) {
  const epic = useStore((s) => s.getEpic(epicId));
  const tickets = useStore((s) => s.getTicketsByEpic(epicId));
  const agents = useStore((s) => s.agents);

  if (!epic) return <div className="empty-state">Epic not found</div>;

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

  const getAgentName = (agentId) => {
    if (!agentId) return 'unassigned';
    const agent = agents.find((a) => a.id === agentId);
    return agent ? agent.name : 'unknown';
  };

  return (
    <div>
      <div className="epic-detail__header">
        <div className="epic-detail__name">{epic.name}</div>
        <div className="epic-detail__desc">{epic.description}</div>
        <div className="sprint-detail__meta project-header__desc">
          <div className="ticket-detail__meta-item">
            <span className="ticket-detail__meta-label">Status:</span>
            <StatusBadge status={epic.status} />
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

export default EpicDetail;
