// Path: src/components/project/LiveSessions.jsx
// File: LiveSessions.jsx
// Created: 2026-04-09
// Purpose: Team status panel - per-project agent roster. Liveness is driven by the DB-authoritative GET /api/projects/{id}/team endpoint (presumed_live + last_seen, shipped in DWB-387), replacing the prior ticket-derived heuristic. Columns: status dot from presumed_live, name, role-bucket, last_seen ("3m ago"), current ticket (still from store tickets where status === 'in_progress'). The stale-ticket POST to /api/tickets/stale-check remains here (10/20/30 min thresholds) since it's tightly coupled to this view's agent/ticket join.
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useRef), react-router-dom (Link), store/useStore, api/projectAgents (getProjectTeam), config (API_BASE_URL), styles/hooks.css
// Data In: projectId prop
// Data Out: Default export LiveSessions component
// Last Modified: 2026-06-12

import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { getProjectTeam } from '../../api/projectAgents';
import { API_BASE_URL } from '../../config';
import '../../styles/hooks.css';

const TICK_MS = 1000;
const TEAM_REFRESH_MS = 30_000;

function formatLastSeen(iso) {
  if (!iso) return 'never';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const t = new Date(ts).getTime();
  if (isNaN(t)) return 'never';
  const ms = Date.now() - t;
  if (ms < 30_000) return 'just now';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

function roleBucket(role) {
  if (role === 'team-lead') return 'TL';
  if (role === 'pm') return 'PM';
  return 'Worker';
}

function LiveSessions({ projectId }) {
  const tickets = useStore((s) => s.tickets);
  const [team, setTeam] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [, setTick] = useState(0);
  const staleAlertedRef = useRef({});

  const projectTickets = tickets.filter(
    (t) => t.project_id === Number(projectId) && t.status === 'in_progress'
  );
  const hasWorking = projectTickets.length > 0;

  // Refs so the 1s tick callback always reads the latest snapshot of these
  // arrays without re-binding the interval.
  const projectTicketsRef = useRef(projectTickets);
  projectTicketsRef.current = projectTickets;
  const teamRef = useRef(team);
  teamRef.current = team;

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const data = await getProjectTeam(projectId);
        if (cancelled) return;
        setTeam(Array.isArray(data?.agents) ? data.agents : []);
      } catch {
        if (!cancelled) setTeam([]);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    refresh();
    const id = setInterval(refresh, TEAM_REFRESH_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [projectId]);

  useEffect(() => {
    const id = setInterval(() => {
      setTick((t) => t + 1);

      // Stale-ticket detection at 10/20/30+ min thresholds. Logic preserved
      // from the prior implementation; only the agent lookup source changed.
      const currentTickets = projectTicketsRef.current;
      const currentAgents = teamRef.current;
      const currentIds = new Set(currentTickets.map((t) => t.id));

      for (const ticketId of Object.keys(staleAlertedRef.current)) {
        if (!currentIds.has(Number(ticketId))) {
          delete staleAlertedRef.current[ticketId];
        }
      }

      currentTickets.forEach((ticket) => {
        if (!ticket.updated_at) return;
        const ts = ticket.updated_at.endsWith('Z') ? ticket.updated_at : ticket.updated_at + 'Z';
        const elapsedMinutes = (Date.now() - new Date(ts).getTime()) / 60000;
        const currentThreshold = Math.floor(elapsedMinutes / 10) * 10;
        const lastAlerted = staleAlertedRef.current[ticket.id] || 0;

        if (currentThreshold >= 10 && currentThreshold > lastAlerted) {
          staleAlertedRef.current[ticket.id] = currentThreshold;
          const agent = currentAgents.find((a) => a.agent_id === ticket.assigned_agent_id);
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
    }, TICK_MS);
    return () => clearInterval(id);
  }, [hasWorking]);

  if (!loaded) {
    return (
      <div className="live-sessions">
        <div className="live-sessions__empty">Loading team...</div>
      </div>
    );
  }

  if (team.length === 0) {
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
        <span className="live-sessions__col-time">Last Seen</span>
        <span className="live-sessions__col-ticket">Current Ticket</span>
      </div>
      {team.map((agent) => {
        const agentTickets = projectTickets
          .filter((t) => t.assigned_agent_id === agent.agent_id)
          .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0));
        const currentTicket = agentTickets[0] || null;
        const live = !!agent.presumed_live;

        return (
          <div key={agent.agent_id} className={`live-sessions__row${live ? ' live-sessions__row--active' : ''}`}>
            <span className="live-sessions__col-status">
              <span className={`live-sessions__dot${live ? '' : ' live-sessions__dot--inactive'}`} />
            </span>
            <span className="live-sessions__col-name">{agent.name}</span>
            <span className="live-sessions__col-type">{roleBucket(agent.role)}</span>
            <span className="live-sessions__col-time">{formatLastSeen(agent.last_seen)}</span>
            <span className="live-sessions__col-ticket">
              {currentTicket ? (
                <Link to={`/projects/${projectId}/tickets/${currentTicket.id}`}>
                  {currentTicket.ticket_key}
                </Link>
              ) : '-'}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default LiveSessions;
