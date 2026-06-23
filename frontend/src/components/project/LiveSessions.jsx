// Path: src/components/project/LiveSessions.jsx
// File: LiveSessions.jsx
// Created: 2026-04-09
// Purpose: Team status panel - per-project agent roster rendered as a scoring leaderboard (DWB-428, ranking columns DWB-433). Liveness is driven by the DB-authoritative GET /api/projects/{id}/team endpoint (presumed_live + last_seen, shipped in DWB-387). Scoring (rank, reputation, this-sprint delta, influence remaining, tier) is joined in from GET /api/projects/{id}/scores (DWB-424), which already returns the full roster sorted top-first; rows are reordered to preserve that leaderboard order. Columns: status dot from presumed_live, rank #, name, role-bucket, reputation, sprint delta, influence, tier label, last_seen ("3m ago"), current ticket (from store tickets where status === 'in_progress'). The #1 and last-place rows are visually accented. The stale-ticket POST to /api/tickets/stale-check remains here (10/20/30 min thresholds) since it's tightly coupled to this view's agent/ticket join.
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect, useRef), react-router-dom (Link), store/useStore, api/projectAgents (getProjectTeam), api/scores (getProjectScores), utils/scoring, config (API_BASE_URL), styles/hooks.css
// Data In: projectId prop
// Data Out: Default export LiveSessions component
// Last Modified: 2026-06-23

import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import { getProjectTeam } from '../../api/projectAgents';
import { getProjectScores } from '../../api/scores';
import { tierLabel, rowRank, isTopRow, isBottomRow } from '../../utils/scoring';
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

function formatDelta(delta) {
  const n = Number(delta) || 0;
  if (n > 0) return `+${n}`;
  return `${n}`;
}

function deltaClass(delta) {
  const n = Number(delta) || 0;
  if (n > 0) return ' live-sessions__col-delta--up';
  if (n < 0) return ' live-sessions__col-delta--down';
  return '';
}

function LiveSessions({ projectId }) {
  const tickets = useStore((s) => s.tickets);
  const [team, setTeam] = useState([]);
  const [scores, setScores] = useState([]);
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
        const [data, scoreRows] = await Promise.all([
          getProjectTeam(projectId),
          getProjectScores(projectId).catch(() => []),
        ]);
        if (cancelled) return;
        setTeam(Array.isArray(data?.agents) ? data.agents : []);
        setScores(Array.isArray(scoreRows) ? scoreRows : []);
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

  // Join scores to the roster and reorder rows to preserve the leaderboard
  // order returned by the API (already sorted top-first). Agents missing from
  // the scores payload fall to the bottom; defaults match an unscored agent.
  const scoreByAgent = {};
  scores.forEach((s, i) => {
    scoreByAgent[s.agent_id] = { ...s, _order: i };
  });
  const orderedTeam = [...team].sort((a, b) => {
    const ra = scoreByAgent[a.agent_id]?._order ?? Number.MAX_SAFE_INTEGER;
    const rb = scoreByAgent[b.agent_id]?._order ?? Number.MAX_SAFE_INTEGER;
    return ra - rb;
  });
  const total = orderedTeam.length;

  return (
    <div className="live-sessions live-sessions--scored">
      <div className="live-sessions__header">
        <span className="live-sessions__col-status">Status</span>
        <span className="live-sessions__col-rank">#</span>
        <span className="live-sessions__col-name">Name</span>
        <span className="live-sessions__col-type">Type</span>
        <span className="live-sessions__col-num">Rep</span>
        <span className="live-sessions__col-num">Sprint</span>
        <span className="live-sessions__col-num">Infl</span>
        <span className="live-sessions__col-tier">Tier</span>
        <span className="live-sessions__col-time">Last Seen</span>
        <span className="live-sessions__col-ticket">Current Ticket</span>
      </div>
      {orderedTeam.map((agent, i) => {
        const score = scoreByAgent[agent.agent_id] || { reputation: 0, sprint_delta: 0, influence: 20 };
        const agentTickets = projectTickets
          .filter((t) => t.assigned_agent_id === agent.agent_id)
          .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0));
        const currentTicket = agentTickets[0] || null;
        const live = !!agent.presumed_live;
        const top = isTopRow(score, i, total);
        const bottom = isBottomRow(score, i, total);
        const rankClass = top
          ? ' live-sessions__row--top'
          : bottom
            ? ' live-sessions__row--bottom'
            : '';
        const label = tierLabel(score.tier);

        return (
          <div key={agent.agent_id} className={`live-sessions__row${live ? ' live-sessions__row--active' : ''}${rankClass}`}>
            <span className="live-sessions__col-status">
              <span className={`live-sessions__dot${live ? '' : ' live-sessions__dot--inactive'}`} />
            </span>
            <span className="live-sessions__col-rank">{rowRank(score, i)}</span>
            <span className="live-sessions__col-name">{agent.name}</span>
            <span className="live-sessions__col-type">{roleBucket(agent.role)}</span>
            <span className="live-sessions__col-num">{score.reputation}</span>
            <span className={`live-sessions__col-num live-sessions__col-delta${deltaClass(score.sprint_delta)}`}>
              {formatDelta(score.sprint_delta)}
            </span>
            <span className="live-sessions__col-num">{score.influence}</span>
            <span className="live-sessions__col-tier">{label || '-'}</span>
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
