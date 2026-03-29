// Path: src/components/project/ActivityFeed.jsx
// File: ActivityFeed.jsx
// Created: 2026-03-29
// Purpose: Live-polling activity feed showing recent project events with columnar layout and relative timestamps
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useRef), api/activityFeed (getActivityFeed)
// Data In: projectId prop
// Data Out: default export ActivityFeed component
// Last Modified: 2026-03-29

import { useState, useEffect, useRef } from 'react';
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

function formatActivity(entry) {
  const action = entry.action || 'updated';
  const type = entry.entity_type || '';
  const detail = typeof entry.details === 'object' && entry.details !== null
    ? (entry.details.summary || entry.details.title || entry.details.message || '')
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
          <div key={entry.id} className="activity-feed__entry">
            <span className="activity-feed__col-time">{timeAgo(entry.created_at)}</span>
            <span className="activity-feed__col-activity">{formatActivity(entry)}</span>
            <span className="activity-feed__col-worker">{entry.agent_name || 'system'}</span>
            <span className="activity-feed__col-role">{entry.agent_role || ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ActivityFeed;
