// Path: src/components/agents/AgentMemoryPanel.jsx
// File: AgentMemoryPanel.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: Per-agent human_memory view - the four tiers (CORE / SCAR /
//          SCAR_CONTEXT_BOUND / WORKING), each memory's DERIVED score and
//          band, and the untiered/unscored rows reported with a reason
//          rather than dropped. Data from GET /agents/:id/memory/scored
//          (DWB-585), which is the only source of truth for the score -
//          this component computes nothing itself.
// Caller: pages/AgentPage.jsx
// Callees: react (useState, useEffect), api/memory (getScoredMemory)
// Data In: agentId prop
// Data Out: Default export AgentMemoryPanel component
// Last Modified: 2026-09-30 (DWB-613: comment updated for Miles's injection-vs-consultation ruling - this panel must never be on a consulting path, not merely never on a poll)

import { useState, useEffect } from 'react';
import { getScoredMemory } from '../../api/memory';

const TIER_ORDER = ['core', 'scar', 'scar_context_bound', 'working'];

const TIER_LABEL = {
  core: 'CORE',
  scar: 'SCAR',
  scar_context_bound: 'SCAR (context-bound)',
  working: 'WORKING',
};

const BAND_LABEL = {
  full_text: 'full text',
  compressed: 'compressed',
  demotion_candidate: 'demotion candidate',
  last_consolidation: 'last pass',
};

const BAND_CLASS = {
  full_text: 'memory-panel__band--full',
  compressed: 'memory-panel__band--compressed',
  demotion_candidate: 'memory-panel__band--demote',
  last_consolidation: 'memory-panel__band--evict',
};

const REASON_LABEL = {
  untiered: 'awaiting consolidation',
  no_session_origin: 'no session to count from',
};

const NOT_COMPUTED_LABEL = {
  project_not_in_human_memory_mode: 'this project runs stock memory, not human_memory',
  project_has_no_project: 'this agent has no project',
  agent_has_no_project: 'this agent has no project',
};

function truncate(body, max = 140) {
  const oneLine = (body || '').replace(/\s+/g, ' ').trim();
  if (oneLine.length <= max) return oneLine;
  return oneLine.slice(0, max - 1).trimEnd() + '…';
}

function AgentMemoryPanel({ agentId }) {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);

  // Miles's ruling (2026-09-30, after DWB-610/612/603): a read only fires if
  // it is a deliberate "have I made this scar-producing error before?" check
  // made OUTSIDE normal startup. A panel showing an agent its own memories is
  // injection-shaped, not consultation-shaped, same as spawn/SessionStart -
  // nobody asked a question here, something is just being displayed. So this
  // component must NEVER sit on a consulting path, full stop, independent of
  // whether it polls.
  //
  // DO NOT add this effect's data source to the app's poll cycle (useAppData)
  // or otherwise re-fetch on an interval either - belt and suspenders. GET
  // /agents/:id/memory/scored is NOT side-effect-free today: reading it fires
  // every scar-family row it returns (DWB-603's _fire_scars, the only write
  // site for fired_count), so until Stan moves that firing off the plain read
  // path (per the ruling above), a component that polls this endpoint would
  // promote a project's entire scar store toward CORE in minutes just by
  // being left open. Fetch only on agentId change, as below.
  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    getScoredMemory(agentId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => { cancelled = true; };
  }, [agentId]);

  if (!loaded) {
    return (
      <div className="agent-detail__section" data-testid="agent-memory-panel">
        <div className="agent-detail__section-title">Memory</div>
        <div className="memory-panel__empty">Loading memory...</div>
      </div>
    );
  }

  if (!data || !data.computed) {
    const reason = data?.reason ? NOT_COMPUTED_LABEL[data.reason] || data.reason : null;
    return (
      <div className="agent-detail__section" data-testid="agent-memory-panel">
        <div className="agent-detail__section-title">Memory</div>
        <div className="memory-panel__empty">
          {reason ? `Not computed: ${reason}` : 'No memory data'}
        </div>
      </div>
    );
  }

  const byTier = {};
  const unscored = [];
  for (const entry of data.entries) {
    if (!entry.scored) {
      unscored.push(entry);
      continue;
    }
    (byTier[entry.tier] = byTier[entry.tier] || []).push(entry);
  }
  for (const list of Object.values(byTier)) {
    list.sort((a, b) => (b.score || 0) - (a.score || 0));
  }

  const nothingAtAll = data.entries.length === 0;

  return (
    <div className="agent-detail__section" data-testid="agent-memory-panel">
      <div className="agent-detail__section-title">Memory</div>

      <div className="memory-panel__summary">
        <span className="memory-panel__stat">
          <span className="memory-panel__stat-value" data-testid="memory-demote-count">{data.demote.length}</span>
          <span className="memory-panel__stat-label">demotion candidates</span>
        </span>
        <span className="memory-panel__stat">
          <span className="memory-panel__stat-value" data-testid="memory-evict-count">{data.evict.length}</span>
          <span className="memory-panel__stat-label">at last pass</span>
        </span>
        <span className="memory-panel__stat">
          <span className="memory-panel__stat-value" data-testid="memory-promote-count">{data.promote.length}</span>
          <span className="memory-panel__stat-label">journal entries ready to promote</span>
        </span>
      </div>

      {nothingAtAll ? (
        <div className="memory-panel__empty">No memories yet</div>
      ) : (
        <>
          {TIER_ORDER.filter((tier) => byTier[tier]?.length).map((tier) => (
            <div className="memory-panel__tier" key={tier}>
              <div className="memory-panel__tier-title">
                {TIER_LABEL[tier]}
                <span className="memory-panel__tier-count">{byTier[tier].length}</span>
              </div>
              <table className="data-table" data-testid={`memory-tier-${tier}`}>
                <thead>
                  <tr>
                    <th>Score</th>
                    <th>Band</th>
                    <th>Sessions since reinforced</th>
                    <th>Fired</th>
                    <th>Memory</th>
                  </tr>
                </thead>
                <tbody>
                  {byTier[tier].map((entry) => (
                    <tr key={entry.id}>
                      <td>{entry.score}</td>
                      <td>
                        <span className={`memory-panel__band ${BAND_CLASS[entry.band] || ''}`}>
                          {BAND_LABEL[entry.band] || entry.band}
                        </span>
                      </td>
                      <td>{entry.sessions_since_reinforced}</td>
                      <td>{entry.fired_count}</td>
                      <td className="memory-panel__body">{truncate(entry.body)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}

          {unscored.length > 0 && (
            <div className="memory-panel__tier">
              <div className="memory-panel__tier-title">
                Unscored
                <span className="memory-panel__tier-count">{unscored.length}</span>
              </div>
              <table className="data-table" data-testid="memory-tier-unscored">
                <thead>
                  <tr>
                    <th>Reason</th>
                    <th>Memory</th>
                  </tr>
                </thead>
                <tbody>
                  {unscored.map((entry) => (
                    <tr key={entry.id}>
                      <td>{REASON_LABEL[entry.reason] || entry.reason}</td>
                      <td className="memory-panel__body">{truncate(entry.body)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default AgentMemoryPanel;
