// Path: src/components/project/Scoreboard.jsx
// File: Scoreboard.jsx
// Created: 2026-06-23
// Purpose: Full per-project scoring leaderboard (DWB-433) with inline carrot/stick controls (DWB-434), shown under the Scoreboard tab on ProjectAgentsPage. Renders one row per agent with rank #, name (links to that agent's ledger on AgentPage), reputation, signed sprint delta, influence, a tier label, and fixed-amount carrot +10 / stick -10 buttons. Clicking a button expands the row in place to an optional reason field plus an inline "carrot +10? confirm / cancel" (no modal); on confirm it POSTs the award and refreshes the leaderboard, on error it shows the API detail inline beside the row. Top (#1) and last-place rows are visually accented. Data from GET /api/projects/{id}/scores (DWB-424), already sorted top-first; rank + tier read from DWB-432 fields with a position-based fall-back.
// Caller: pages/ProjectAgentsPage.jsx (Scoreboard tab)
// Callees: react (useState, useEffect, useCallback), react-router-dom (Link), api/scores (getProjectScores, awardScore), utils/scoring, styles/score.css
// Data In: projectId prop
// Data Out: Default export Scoreboard component
// Last Modified: 2026-06-23

import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getProjectScores, awardScore } from '../../api/scores';
import { tierLabel, rowRank, formatDelta, deltaDirection, isTopRow, isBottomRow } from '../../utils/scoring';
import '../../styles/score.css';

const CARROT_DELTA = 10;
const STICK_DELTA = -10;

function Scoreboard({ projectId }) {
  const [rows, setRows] = useState([]);
  const [loaded, setLoaded] = useState(false);
  // Pending inline action: { agentId, kind: 'carrot' | 'stick' }.
  const [pending, setPending] = useState(null);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    return getProjectScores(projectId)
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch(() => setRows([]))
      .finally(() => setLoaded(true));
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    getProjectScores(projectId)
      .then((data) => { if (!cancelled) setRows(Array.isArray(data) ? data : []); })
      .catch(() => { if (!cancelled) setRows([]); })
      .finally(() => { if (!cancelled) setLoaded(true); });
    return () => { cancelled = true; };
  }, [projectId]);

  function openAction(agentId, kind) {
    setPending({ agentId, kind });
    setReason('');
    setError(null);
  }

  function cancelAction() {
    setPending(null);
    setReason('');
    setError(null);
  }

  async function confirmAction(row) {
    const delta = pending.kind === 'carrot' ? CARROT_DELTA : STICK_DELTA;
    setSubmitting(true);
    setError(null);
    try {
      await awardScore(projectId, { agent: row.agent_name, delta, reason });
      await load();
      setPending(null);
      setReason('');
    } catch (err) {
      setError(err?.message || 'Award failed');
    } finally {
      setSubmitting(false);
    }
  }

  if (!loaded) {
    return <div className="scoreboard__empty">Loading scoreboard...</div>;
  }

  if (rows.length === 0) {
    return <div className="scoreboard__empty">No scores yet</div>;
  }

  const total = rows.length;

  return (
    <div className="scoreboard">
      <div className="scoreboard__header">
        <span className="scoreboard__col-rank">#</span>
        <span className="scoreboard__col-name">Name</span>
        <span className="scoreboard__col-tier">Tier</span>
        <span className="scoreboard__col-num">Rep</span>
        <span className="scoreboard__col-num">Sprint</span>
        <span className="scoreboard__col-num">Infl</span>
        <span className="scoreboard__col-actions">Adjust</span>
      </div>
      {rows.map((row, i) => {
        const top = isTopRow(row, i, total);
        const bottom = isBottomRow(row, i, total);
        const rowClass = top
          ? ' scoreboard__row--top'
          : bottom
            ? ' scoreboard__row--bottom'
            : '';
        const label = tierLabel(row.tier);
        const active = pending && pending.agentId === row.agent_id;
        const actionDelta = active
          ? (pending.kind === 'carrot' ? CARROT_DELTA : STICK_DELTA)
          : 0;

        return (
          <div key={row.agent_id} className="scoreboard__group">
            <div className={`scoreboard__row${rowClass}`}>
              <span className="scoreboard__col-rank">{rowRank(row, i)}</span>
              <span className="scoreboard__col-name">
                <Link to={`/projects/${projectId}/agents/${row.agent_id}`}>{row.agent_name}</Link>
              </span>
              <span className="scoreboard__col-tier">{label || '-'}</span>
              <span className="scoreboard__col-num">{row.reputation}</span>
              <span className={`scoreboard__col-num scoreboard__delta--${deltaDirection(row.sprint_delta)}`}>
                {formatDelta(row.sprint_delta)}
              </span>
              <span className="scoreboard__col-num">{row.influence}</span>
              <span className="scoreboard__col-actions">
                {!active && (
                  <>
                    <button
                      className="scoreboard__btn scoreboard__btn--carrot"
                      onClick={() => openAction(row.agent_id, 'carrot')}
                    >
                      carrot +{CARROT_DELTA}
                    </button>
                    <button
                      className="scoreboard__btn scoreboard__btn--stick"
                      onClick={() => openAction(row.agent_id, 'stick')}
                    >
                      stick {STICK_DELTA}
                    </button>
                  </>
                )}
              </span>
            </div>
            {active && (
              <div className="scoreboard__confirm">
                <input
                  type="text"
                  className="scoreboard__reason"
                  placeholder="reason (optional)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  disabled={submitting}
                  autoFocus
                />
                <span className="scoreboard__confirm-line">
                  {pending.kind === 'carrot' ? 'carrot' : 'stick'} {formatDelta(actionDelta)}?
                  <button
                    className="scoreboard__btn scoreboard__btn--confirm"
                    onClick={() => confirmAction(row)}
                    disabled={submitting}
                  >
                    {submitting ? 'sending...' : 'confirm'}
                  </button>
                  <span className="scoreboard__sep">/</span>
                  <button
                    className="scoreboard__btn scoreboard__btn--cancel"
                    onClick={cancelAction}
                    disabled={submitting}
                  >
                    cancel
                  </button>
                </span>
                {error && <span className="scoreboard__error">{error}</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default Scoreboard;
