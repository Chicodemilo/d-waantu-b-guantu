// Path: src/components/project/ActivityFeed.jsx
// File: ActivityFeed.jsx
// Created: 2026-03-29
// Purpose: Live-polling activity feed showing recent project events with columnar layout, semantic-verb-aware rendering, and relative timestamps
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useRef), react-router-dom (Link), api/activityFeed (getActivityFeed)
// Data In: projectId prop
// Data Out: default export ActivityFeed component
// Last Modified: 2026-06-22

import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { getActivityFeed } from '../../api/activityFeed';

function timeAgo(dateStr) {
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (diff < 60) return 'just now';
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function truncate(str, max = 40) {
  if (!str || str.length <= max) return str;
  return str.slice(0, max) + '…';
}

// Type- and verb-aware activity renderer (DWB-407 + DWB-412).
// The live feed is already scoped to projectId and carries entity_id + the
// denormalized details payload, so ticket links resolve without a store lookup.
// Each row also carries agent_name/agent_role (the actor), rendered in their own
// columns, so the activity cell never repeats the actor name.
// Semantic verbs from log_activity() (DWB-409/410/411) render as human phrases;
// generic CRUD verbs and unknown entity types fall through to plain text.
function renderActivity(entry, projectId) {
  const action = entry.action || 'updated';
  const type = entry.entity_type || '';
  const details = (typeof entry.details === 'object' && entry.details !== null)
    ? entry.details
    : {};

  if (type === 'ticket') {
    const key = details.ticket_key;
    const title = details.title;
    // Semantic ticket rows (status_changed/reopened/assigned) carry only
    // {from,to} or {agent,agent_id}, NOT ticket_key/title, so fall back to a
    // bare "ticket #id" label rather than rendering "undefined".
    const label = key
      ? key + (title ? ' ' + truncate(title) : '')
      : (truncate(title) || `ticket #${entry.entity_id}`);
    const ticketRef = (entry.entity_id && projectId)
      ? (
        <Link
          to={`/projects/${projectId}/tickets/${entry.entity_id}`}
          className="activity-feed__ticket-link"
        >
          {label}
        </Link>
      )
      : label;

    if (action === 'status_changed') {
      const transition = (details.from && details.to)
        ? <> from {details.from} to {details.to}</>
        : null;
      return <>moved {ticketRef}{transition}</>;
    }
    if (action === 'reopened') {
      const transition = (details.from && details.to)
        ? <> ({details.from} to {details.to})</>
        : null;
      return <>reopened {ticketRef}{transition}</>;
    }
    if (action === 'assigned') {
      const who = details.agent || (details.agent_id ? `agent #${details.agent_id}` : 'unassigned');
      return <>assigned {ticketRef} to {who}</>;
    }
    // created / updated / unknown ticket verb: "{action} {ticketRef}".
    return <>{action} {ticketRef}</>;
  }

  if (type === 'alert') {
    return <>{action} alert: {truncate(details.title || details.message || '', 50)}</>;
  }

  if (type === 'sprint') {
    if (action === 'sprint_opened' || action === 'sprint_closed') {
      const verb = action === 'sprint_opened' ? 'opened' : 'closed';
      const num = details.sprint_number != null ? details.sprint_number : '?';
      const goal = details.goal ? `: ${truncate(details.goal, 50)}` : '';
      return <>{verb} sprint {num}{goal}</>;
    }
    return <>{action} {details.name || details.goal || 'sprint'}</>;
  }

  if (type === 'agent') {
    if (action === 'consolidation_acked') {
      return <>acked consolidation (sprint {details.sprint_id})</>;
    }
  }

  if (type === 'session') {
    if (action === 'session_opened') {
      const method = details.open_method ? ` (${details.open_method})` : '';
      return <>opened DWB session #{entry.entity_id}{method}</>;
    }
    if (action === 'session_closed') {
      const headline = details.headline ? `: ${truncate(details.headline, 50)}` : '';
      return <>closed DWB session #{entry.entity_id}{headline}</>;
    }
  }

  // Generic fallback for unknown types: preserve prior plain-text behavior.
  const detail = typeof entry.details === 'object' && entry.details !== null
    ? (details.summary || details.title || details.message || '')
    : (entry.details || '');
  const parts = [action, type];
  if (detail) parts.push(detail);
  return parts.join(' ');
}

function ActivityFeed({ projectId }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      getActivityFeed(projectId)
        .then((data) => {
          if (!cancelled) setEntries(data);
        })
        .catch(() => {})
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    poll();
    timerRef.current = setInterval(poll, 2000);

    return () => {
      cancelled = true;
      clearInterval(timerRef.current);
    };
  }, [projectId]);

  if (loading) return null;

  if (entries.length === 0) {
    return (
      <div className="activity-feed">
        <div className="activity-feed__empty">No recent activity</div>
      </div>
    );
  }

  return (
    <div className="activity-feed">
      <div className="activity-feed__header">
        <span className="activity-feed__col-time">Time</span>
        <span className="activity-feed__col-activity">Activity</span>
        <span className="activity-feed__col-worker">Worker</span>
        <span className="activity-feed__col-role">Role</span>
      </div>
      <div className="activity-feed__scroll">
        {entries.map((entry) => (
          <div key={entry.id} className={`activity-feed__entry${!entry.agent_name || entry.agent_name === 'system' ? ' activity-feed__entry--system' : ''}`}>
            <span className="activity-feed__col-time">{timeAgo(entry.created_at)}</span>
            <span className="activity-feed__col-activity">{renderActivity(entry, projectId)}</span>
            <span className="activity-feed__col-worker">{entry.agent_name || 'system'}</span>
            <span className="activity-feed__col-role">{entry.agent_role || ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ActivityFeed;
