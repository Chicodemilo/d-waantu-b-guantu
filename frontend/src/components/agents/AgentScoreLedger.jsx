// Path: src/components/agents/AgentScoreLedger.jsx
// File: AgentScoreLedger.jsx
// Created: 2026-06-22
// Purpose: Per-agent score ledger panel (DWB-428). Shows the agent's current reputation / influence / this-sprint delta, then the append-only score_event history (newest first): signed delta colored up/down, trigger_type, reason, and for peer events the actor name + influence cost. Reverted rows are visually marked. Data from GET /api/agents/:id/score?project_id= (DWB-424).
// Caller: pages/AgentPage.jsx
// Callees: react (useState, useEffect), api/scores (getAgentScore), styles/score.css
// Data In: agentId, projectId props
// Data Out: Default export AgentScoreLedger component
// Last Modified: 2026-06-22

import { useState, useEffect } from 'react';
import { getAgentScore } from '../../api/scores';
import '../../styles/score.css';

function formatDelta(delta) {
  const n = Number(delta) || 0;
  return n > 0 ? `+${n}` : `${n}`;
}

function deltaClass(delta) {
  const n = Number(delta) || 0;
  if (n > 0) return ' score-ledger__delta--up';
  if (n < 0) return ' score-ledger__delta--down';
  return '';
}

function formatTrigger(trigger) {
  return (trigger || '').replace(/_/g, ' ');
}

function formatTime(iso) {
  if (!iso) return '';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString();
}

function AgentScoreLedger({ agentId, projectId }) {
  const [score, setScore] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    getAgentScore(agentId, projectId)
      .then((data) => {
        if (!cancelled) setScore(data);
      })
      .catch(() => {
        if (!cancelled) setScore(null);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => { cancelled = true; };
  }, [agentId, projectId]);

  if (!loaded) {
    return (
      <div className="agent-detail__section">
        <div className="agent-detail__section-title">Score Ledger</div>
        <div className="score-ledger__empty">Loading score...</div>
      </div>
    );
  }

  if (!score) {
    return (
      <div className="agent-detail__section">
        <div className="agent-detail__section-title">Score Ledger</div>
        <div className="score-ledger__empty">No score data</div>
      </div>
    );
  }

  // Newest first. Sort by created_at, falling back to id for ties / missing dates.
  const ledger = [...(score.ledger || [])].sort((a, b) => {
    const ta = new Date(a.created_at || 0).getTime();
    const tb = new Date(b.created_at || 0).getTime();
    if (tb !== ta) return tb - ta;
    return (b.id || 0) - (a.id || 0);
  });

  return (
    <div className="agent-detail__section">
      <div className="agent-detail__section-title">Score Ledger</div>

      <div className="score-summary">
        <div className="score-summary__item">
          <span className="score-summary__label">Reputation</span>
          <span className="score-summary__value">{score.reputation}</span>
        </div>
        <div className="score-summary__item">
          <span className="score-summary__label">This Sprint</span>
          <span className={`score-summary__value${deltaClass(score.sprint_delta)}`}>
            {formatDelta(score.sprint_delta)}
          </span>
        </div>
        <div className="score-summary__item">
          <span className="score-summary__label">Influence</span>
          <span className="score-summary__value">{score.influence}</span>
        </div>
      </div>

      {ledger.length === 0 ? (
        <div className="score-ledger__empty">No score events yet</div>
      ) : (
        <div className="score-ledger">
          <div className="score-ledger__header">
            <span className="score-ledger__col-delta">Delta</span>
            <span className="score-ledger__col-trigger">Trigger</span>
            <span className="score-ledger__col-reason">Reason</span>
            <span className="score-ledger__col-time">When</span>
          </div>
          {ledger.map((event) => {
            const reverted = event.reverted_by != null;
            const isPeer = event.source === 'peer';
            return (
              <div
                key={event.id}
                className={`score-ledger__row${reverted ? ' score-ledger__row--reverted' : ''}`}
              >
                <span className={`score-ledger__col-delta${deltaClass(event.delta)}`}>
                  {formatDelta(event.delta)}
                </span>
                <span className="score-ledger__col-trigger">
                  {formatTrigger(event.trigger_type)}
                  <span className="score-ledger__source">{event.source}</span>
                  {reverted && <span className="score-ledger__reverted-tag">reverted</span>}
                </span>
                <span className="score-ledger__col-reason">
                  {event.reason || '-'}
                  {isPeer && event.actor_name && (
                    <span className="score-ledger__actor">
                      by {event.actor_name} (cost {event.actor_cost})
                    </span>
                  )}
                </span>
                <span className="score-ledger__col-time">{formatTime(event.created_at)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default AgentScoreLedger;
