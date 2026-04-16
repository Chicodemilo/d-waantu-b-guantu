// Path: src/components/project/LiveSessions.jsx
// File: LiveSessions.jsx
// Created: 2026-04-09
// Purpose: Team status panel — shows all project agents with live/offline status, elapsed time, and current ticket
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect), react-router-dom (Link), store/useStore, styles/hooks.css
// Data In: projectId prop
// Data Out: Default export LiveSessions component
// Last Modified: 2026-04-16

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import '../../styles/hooks.css';

function formatElapsed(startTime) {
  const ts = startTime.endsWith('Z') ? startTime : startTime + 'Z';
  const elapsed = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (elapsed < 0) return '0s';
  const hrs = Math.floor(elapsed / 3600);
  const mins = Math.floor((elapsed % 3600) / 60);
  const secs = elapsed % 60;
  if (hrs > 0) return `${hrs}h ${mins}m`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

function LiveSessions({ projectId }) {
  const agents = useStore((s) => s.getAgentsByProject(projectId));
  const sessions = useStore((s) => s.getHookSessionsByProject(projectId));
  const tickets = useStore((s) => s.tickets);
  const activeSessions = sessions.filter((s) => s.status === 'active');
  const [, setTick] = useState(0);

  const hasActive = activeSessions.length > 0;
  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [hasActive]);

  if (agents.length === 0) {
    return (
      <div className="live-sessions">
        <div className="live-sessions__empty">No team members assigned</div>
      </div>
    );
  }

  const activeSessionByAgent = {};
  for (const s of activeSessions) {
    if (s.agent_id) {
      activeSessionByAgent[s.agent_id] = s;
    }
  }

  return (
    <div className="live-sessions">
      <div className="live-sessions__header">
        <span className="live-sessions__col-status">Status</span>
        <span className="live-sessions__col-name">Name</span>
        <span className="live-sessions__col-type">Type</span>
        <span className="live-sessions__col-time">Time Up</span>
        <span className="live-sessions__col-ticket">Current Ticket</span>
      </div>
      {agents.map((agent) => {
        const session = activeSessionByAgent[agent.id];
        const isActive = !!session;
        const type = agent.role === 'team-lead' ? 'TL'
          : agent.role === 'pm' ? 'PM'
          : 'Worker';
        const inProgressTicket = tickets.find(
          (t) => t.assigned_agent_id === agent.id && t.status === 'in_progress'
        );

        return (
          <div key={agent.id} className={`live-sessions__row${isActive ? ' live-sessions__row--active' : ''}`}>
            <span className="live-sessions__col-status">
              <span className={`live-sessions__dot${isActive ? '' : ' live-sessions__dot--inactive'}`} />
            </span>
            <span className="live-sessions__col-name">{agent.name}</span>
            <span className="live-sessions__col-type">{type}</span>
            <span className="live-sessions__col-time">
              {isActive && session.start_time ? formatElapsed(session.start_time) : '\u2014'}
            </span>
            <span className="live-sessions__col-ticket">
              {inProgressTicket ? (
                <Link to={`/projects/${projectId}/tickets/${inProgressTicket.id}`}>
                  {inProgressTicket.ticket_key}
                </Link>
              ) : '\u2014'}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default LiveSessions;
