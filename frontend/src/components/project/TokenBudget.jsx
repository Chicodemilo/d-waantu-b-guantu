// Path: src/components/project/TokenBudget.jsx
// File: TokenBudget.jsx
// Created: 2026-04-17
// Purpose: Collapsible token budget panel showing per-file token counts vs ceilings with status indicators
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect), config (API_BASE_URL), styles/dashboard.css
// Data In: projectId prop
// Data Out: default export TokenBudget component
// Last Modified: 2026-04-17

import { useState, useEffect } from 'react';
import { API_BASE_URL } from '../../config';
import '../../styles/dashboard.css';

function TokenBudget({ projectId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE_URL}/projects/${projectId}/token-budget`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading || !data) return null;

  const overCount = data.files.filter((f) => f.status === 'over').length;
  const warnCount = data.files.filter((f) => f.status === 'warning').length;

  const statusLabel = overCount > 0
    ? `${overCount} over`
    : warnCount > 0
      ? `${warnCount} warning`
      : '\u2713 all ok';
  const statusClass = overCount > 0
    ? 'token-budget__status--over'
    : warnCount > 0
      ? 'token-budget__status--warning'
      : 'token-budget__status--ok';

  const formatTokens = (n) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(n);
  };

  return (
    <div className="token-budget">
      <button
        className="token-budget__toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`token-budget__caret${expanded ? ' token-budget__caret--open' : ''}`}>&gt;</span>
        token budget
        <span className={`token-budget__status ${statusClass}`}>[{statusLabel}]</span>
      </button>
      {expanded && (
        <div className="token-budget__body">
          <div className="token-budget__summary">
            <span className="token-budget__summary-item">
              total: {formatTokens(data.total_tokens)} tokens across {data.files.length} files
            </span>
            <span className="token-budget__summary-item">
              team startup: ~{formatTokens(data.team_startup_cost)} tokens (5-agent team)
            </span>
          </div>
          <div className="token-budget__list">
            {data.files.map((f) => {
              const pct = f.ceiling > 0 ? Math.round((f.tokens / f.ceiling) * 100) : 0;
              const barWidth = Math.min(pct, 100);
              const barClass = f.status === 'over'
                ? 'token-budget__bar--over'
                : f.status === 'warning'
                  ? 'token-budget__bar--warning'
                  : 'token-budget__bar--ok';
              return (
                <div key={f.path} className="token-budget__file">
                  <div className="token-budget__file-row">
                    <span className={`token-budget__indicator token-budget__indicator--${f.status}`}>
                      {f.status === 'over' ? '\u2717' : f.status === 'warning' ? '\u25CF' : '\u2713'}
                    </span>
                    <span className="token-budget__name">{f.name}</span>
                    <span className="token-budget__count">
                      {formatTokens(f.tokens)}/{formatTokens(f.ceiling)}
                    </span>
                  </div>
                  <div className="token-budget__bar-track">
                    <div
                      className={`token-budget__bar-fill ${barClass}`}
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default TokenBudget;
