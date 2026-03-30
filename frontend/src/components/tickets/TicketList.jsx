// Path: src/components/tickets/TicketList.jsx
// File: TicketList.jsx
// Created: 2026-03-29
// Purpose: Filterable ticket table with backlog toggle, status/type/sprint/epic/agent filters, and navigable rows
// Caller: TicketsPage.jsx
// Callees: react (useState), react-router-dom (useNavigate), useStore, TicketFilters, StatusBadge, tickets.css
// Data In: projectId prop
// Data Out: default export TicketList component
// Last Modified: 2026-03-29

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useStore from '../../store/useStore';
import { formatTime, formatTokens } from '../../utils/format';
import TicketFilters from './TicketFilters';
import StatusBadge from '../common/StatusBadge';
import '../../styles/tickets.css';

function TicketList({ projectId }) {
  const navigate = useNavigate();
  const tickets = useStore((s) => s.getTicketsByProject(projectId));
  const agents = useStore((s) => s.agents);
  const sprints = useStore((s) => s.sprints);
  const epics = useStore((s) => s.epics);
  const [showBacklog, setShowBacklog] = useState(false);
  const [filters, setFilters] = useState({
    status: 'all',
    type: 'all',
    sprint_id: 'all',
    agent_id: 'all',
    epic_id: 'all',
  });

  const getAgentName = (agentId) => {
    if (!agentId) return 'unassigned';
    const agent = agents.find((a) => a.id === agentId);
    return agent ? agent.name : 'unknown';
  };

  const getEpicName = (epicId) => {
    if (!epicId) return '';
    const epic = epics.find((e) => e.id === epicId);
    return epic ? epic.name : '';
  };

  const getSprintName = (sprintId) => {
    if (!sprintId) return '';
    const sprint = sprints.find((s) => s.id === sprintId);
    return sprint ? `S${sprint.sprint_number}: ${sprint.name}` : '';
  };

  let filtered = tickets;
  if (!showBacklog && filters.status === 'all') {
    filtered = filtered.filter((t) => t.status !== 'backlog');
  }
  if (filters.status !== 'all') {
    filtered = filtered.filter((t) => t.status === filters.status);
  }
  if (filters.type !== 'all') {
    filtered = filtered.filter((t) => t.ticket_type === filters.type);
  }
  if (filters.sprint_id !== 'all') {
    filtered = filtered.filter((t) => t.sprint_id === Number(filters.sprint_id));
  }
  if (filters.agent_id !== 'all') {
    filtered = filtered.filter((t) => t.assigned_agent_id === Number(filters.agent_id));
  }
  if (filters.epic_id !== 'all') {
    filtered = filtered.filter((t) => t.epic_id === Number(filters.epic_id));
  }

  return (
    <div>
      <div className="ticket-list__header">
        <span className="ticket-list__count">
          {filtered.length} ticket{filtered.length !== 1 ? 's' : ''}
        </span>
        <button
          className="sidebar__archive-toggle"
          onClick={() => setShowBacklog(!showBacklog)}
        >
          {showBacklog ? '[hide backlog]' : '[show backlog]'}
        </button>
      </div>
      <TicketFilters projectId={projectId} filters={filters} onChange={setFilters} />
      <div className="ticket-list">
        <div className="ticket-row ticket-row--header">
          <span className="ticket-row__key">Key</span>
          <span className="ticket-row__title">Title</span>
          <span>Status</span>
          <span className="ticket-row__type">Type</span>
          <span className="ticket-row__sprint">Sprint</span>
          <span className="ticket-row__epic">Epic</span>
          <span className="ticket-row__agent">Agent</span>
          <span className="ticket-row__tokens">Tokens</span>
          <span className="ticket-row__time">Time</span>
        </div>
        {filtered.map((ticket) => (
          <div
            key={ticket.id}
            className="ticket-row"
            onClick={() => navigate(`/projects/${projectId}/tickets/${ticket.id}`)}
          >
            <span className="ticket-row__key">{ticket.ticket_key}</span>
            <span className="ticket-row__title">{ticket.title}</span>
            <StatusBadge status={ticket.status} />
            <span className="ticket-row__type">{ticket.ticket_type}</span>
            <span className="ticket-row__sprint">{getSprintName(ticket.sprint_id)}</span>
            <span className="ticket-row__epic">{getEpicName(ticket.epic_id)}</span>
            <span className="ticket-row__agent">{getAgentName(ticket.assigned_agent_id)}</span>
            <span className="ticket-row__tokens">{formatTokens(ticket.tokens_used)}</span>
            <span className="ticket-row__time">{formatTime(ticket.time_spent_seconds)}</span>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="empty-state">No tickets match the current filters</div>
        )}
      </div>
    </div>
  );
}

export default TicketList;
