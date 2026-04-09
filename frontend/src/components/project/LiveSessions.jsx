// Path: src/components/project/LiveSessions.jsx
// File: LiveSessions.jsx
// Created: 2026-04-09
// Purpose: Displays active hook sessions for a project with pulsing status dot and elapsed time
// Caller: ProjectPage.jsx
// Callees: store/useStore, styles/hooks.css
// Data In: projectId prop
// Data Out: Default export LiveSessions component
// Last Modified: 2026-04-09

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import '../../styles/hooks.css';

function formatElapsed(startTime) {
  const elapsed = Math.floor((Date.now() - new Date(startTime).getTime()) / 1000);
  if (elapsed < 0) return '0s';
  const hrs = Math.floor(elapsed / 3600);
  const mins = Math.floor((elapsed % 3600) / 60);
  const secs = elapsed % 60;
  if (hrs > 0) return `${hrs}h ${mins}m`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

function LiveSessions({ projectId }) {
  const sessions = useStore((s) => s.getHookSessionsByProject(projectId));
  const activeSessions = sessions.filter((s) => s.status === 'active');
  const [, setTick] = useState(0);

  useEffect(() => {
    if (activeSessions.length === 0) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [activeSessions.length]);

  if (activeSessions.length === 0) {
    return (
      <div className="live-sessions">
        <div className="live-sessions__empty">No active sessions</div>
      </div>
    );
  }

  return (
    <div className="live-sessions">
      {activeSessions.map((session) => (
        <div key={session.id} className="live-sessions__item">
          <div className="live-sessions__dot" />
          <span className="live-sessions__agent">
            {session.agent_name || 'Unknown'}
          </span>
          <span className="live-sessions__type">
            {session.session_type || 'session'}
          </span>
          <span className="live-sessions__elapsed">
            {formatElapsed(session.start_time)}
          </span>
          <span className="live-sessions__tokens">
            {session.total_tokens > 0
              ? `${(session.total_tokens / 1000).toFixed(1)}k tokens`
              : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

export default LiveSessions;
