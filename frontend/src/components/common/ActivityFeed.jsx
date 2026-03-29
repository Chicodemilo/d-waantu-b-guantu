// Path: src/components/common/ActivityFeed.jsx
// File: ActivityFeed.jsx
// Created: 2026-03-29
// Purpose: Displays a chronological feed of recent activity log entries with agent names and ticket links
// Caller: None currently (available for use)
// Callees: react-router-dom (Link), useStore, common.css
// Data In: props { projectId, limit }; activityLog, agents, tickets from store
// Data Out: default export ActivityFeed component
// Last Modified: 2026-03-29

import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import '../../styles/common.css';

function truncate(str, max = 40) {
  if (!str || str.length <= max) return str;
  return str.slice(0, max) + '…';
}

function ActivityFeed({ projectId, limit = 10 }) {
  const activityLog = useStore((s) => s.activityLog);
  const agents = useStore((s) => s.agents);
  const tickets = useStore((s) => s.tickets);

  let items = projectId
    ? activityLog.filter((a) => a.project_id === Number(projectId))
    : activityLog;

  items = items.slice(0, limit);

  const getAgentName = (agentId) => {
    const agent = agents.find((a) => a.id === agentId);
    return agent ? agent.name : 'unknown';
  };

  const getTicketLink = (details, pId) => {
    const key = details?.ticket_key;
    const title = details?.title;
    if (!key) return null;
    const ticket = tickets.find((t) => t.ticket_key === key);
    const ticketProjectId = ticket ? ticket.project_id : pId;
    const ticketId = ticket ? ticket.id : null;
    const label = key + (title ? ' ' + truncate(title) : '');
    if (ticketId && ticketProjectId) {
      return (
        <Link to={`/projects/${ticketProjectId}/tickets/${ticketId}`} className="activity-item__ticket-link">
          {label}
        </Link>
      );
    }
    return <span className="activity-item__entity">{label}</span>;
  };

  const formatTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const describeAction = (item) => {
    const details = item.details || {};
    const ticketLink = getTicketLink(details, item.project_id);

    if (item.entity_type === 'ticket' && ticketLink) {
      return <>{item.action} {ticketLink}</>;
    }

    if (item.entity_type === 'alert') {
      return <>{item.action} alert: {truncate(details.title, 50)}</>;
    }

    if (item.entity_type === 'sprint') {
      return <>{item.action} {details.name || 'sprint'}</>;
    }

    return `${item.action} ${item.entity_type}`;
  };

  return (
    <div className="activity-feed">
      <div className="activity-feed__title">Recent Activity</div>
      {items.length === 0 && (
        <div className="empty-state">No recent activity</div>
      )}
      {items.map((item) => (
        <div key={item.id} className="activity-item">
          <span className="activity-item__time">{formatTime(item.created_at)}</span>
          <span className="activity-item__agent">{getAgentName(item.agent_id)}</span>
          <span className="activity-item__action">{describeAction(item)}</span>
        </div>
      ))}
    </div>
  );
}

export default ActivityFeed;
