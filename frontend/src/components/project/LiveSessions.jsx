// Path: src/components/project/LiveSessions.jsx
// File: LiveSessions.jsx
// Created: 2026-04-09
// Purpose: Team status panel — shows all project agents, working status driven by in_progress tickets, elapsed time since ticket update, stale ticket detection at 10-min intervals
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useRef), react-router-dom (Link), store/useStore, config (API_BASE_URL), styles/hooks.css
// Data In: projectId prop
// Data Out: Default export LiveSessions component
// Last Modified: 2026-04-17

import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { API_BASE_URL } from '../../config';
import '../../styles/hooks.css';

function formatElapsed(timestamp) {
  const ts = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z';
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
  const tickets = useStore((s) => s.tickets);
  const [, setTick] = useState(0);
  const staleAlertedRef = useRef({});

  const projectTickets = tickets.filter(
    (t) => t.project_id === Number(projectId) && t.status === 'in_progress'
  );
  const hasWorking = projectTickets.length > 0;

  // Refs for stale closure safety inside setInterval
  const projectTicketsRef = useRef(projectTickets);
  projectTicketsRef.current = projectTickets;
  const agentsRef = useRef(agents);
  agentsRef.current = agents;

  useEffect(() => {
    if (!hasWorking) return;
    const id = setInterval(() => {
      setTick((t) => t + 1);

      // Stale ticket detection
      const currentTickets = projectTicketsRef.current;
      const currentAgents = agentsRef.current;
      const currentIds = new Set(currentTickets.map((t) => t.id));

      // Clean up entries for tickets no longer in_progress
      for (const ticketId of Object.keys(staleAlertedRef.current)) {
        if (!currentIds.has(Number(ticketId))) {
          delete staleAlertedRef.current[ticketId];
        }
      }

      // Check each in_progress ticket for stale thresholds (10, 20, 30...)
      currentTickets.forEach((ticket) => {
        if (!ticket.updated_at) return;
        const ts = ticket.updated_at.endsWith('Z') ? ticket.updated_at : ticket.updated_at + 'Z';
        const elapsedMinutes = (Date.now() - new Date(ts).getTime()) / 60000;
        const currentThreshold = Math.floor(elapsedMinutes / 10) * 10;
        const lastAlerted = staleAlertedRef.current[ticket.id] || 0;

        if (currentThreshold >= 10 && currentThreshold > lastAlerted) {
          staleAlertedRef.current[ticket.id] = currentThreshold;
          const agent = currentAgents.find((a) => a.id === ticket.assigned_agent_id);
          fetch(`${API_BASE_URL}/tickets/stale-check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ticket_id: ticket.id,
              project_id: ticket.project_id,
              minutes_stale: currentThreshold,
              agent_name: agent ? agent.name : 'unknown',
            }),
          }).catch(() => {});
        }
      });
    }, 1000);
    return () => clearInterval(id);
  }, [hasWorking]);

  if (agents.length === 0) {
    return (
      <div className="live-sessions">
        <div className="live-sessions__empty">No team members assigned</div>
      </div>
    );
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
        const agentTickets = projectTickets
          .filter((t) => t.assigned_agent_id === agent.id)
          .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0));
        const currentTicket = agentTickets[0] || null;
        const isWorking = !!currentTicket;
        const type = agent.role === 'team-lead' ? 'TL'
          : agent.role === 'pm' ? 'PM'
          : 'Worker';

        return (
          <div key={agent.id} className={`live-sessions__row${isWorking ? ' live-sessions__row--active' : ''}`}>
            <span className="live-sessions__col-status">
              <span className={`live-sessions__dot${isWorking ? '' : ' live-sessions__dot--inactive'}`} />
            </span>
            <span className="live-sessions__col-name">{agent.name}</span>
            <span className="live-sessions__col-type">{type}</span>
            <span className="live-sessions__col-time">
              {isWorking && currentTicket.updated_at ? formatElapsed(currentTicket.updated_at) : '\u2014'}
            </span>
            <span className="live-sessions__col-ticket">
              {currentTicket ? (
                <Link to={`/projects/${projectId}/tickets/${currentTicket.id}`}>
                  {currentTicket.ticket_key}
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
