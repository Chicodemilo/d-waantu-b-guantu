import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { getTokenAudit } from '../../api/tokens';
import '../../styles/dashboard.css';

function TokenAudit() {
  const agents = useStore((s) => s.agents);
  const projects = useStore((s) => s.projects);
  const projectAgents = useStore((s) => s.projectAgents);
  const [audit, setAudit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getTokenAudit()
      .then((data) => {
        if (!cancelled) setAudit(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading) return null;
  if (!audit) return null;

  // Build agent name lookup from store
  const agentNameMap = {};
  for (const a of agents) {
    agentNameMap[a.id] = a.name;
  }

  // Find DEMO project IDs to filter out
  const demoProjectIds = new Set(
    projects.filter((p) => (p.prefix || '').toUpperCase() === 'DEMO' || (p.name || '').toUpperCase() === 'DEMO')
      .map((p) => p.id)
  );

  // Agent IDs assigned to DEMO projects
  const demoAgentIds = new Set(
    projectAgents.filter((pa) => demoProjectIds.has(pa.project_id))
      .map((pa) => pa.agent_id)
  );

  const hasDiscrepancies = audit.discrepancies && audit.discrepancies.length > 0;

  return (
    <div className="token-audit">
      <button
        className="token-audit__toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`token-audit__caret${expanded ? ' token-audit__caret--open' : ''}`}>&gt;</span>
        token audit
        {hasDiscrepancies ? (
          <span className="token-audit__status token-audit__status--error">[discrepancies found]</span>
        ) : (
          <span className="token-audit__status token-audit__status--ok">{'\u2713'} clean</span>
        )}
      </button>
      {expanded && (
        <div className="token-audit__body">
          <div className="token-audit__row">
            <span className="token-audit__label">total ticket tokens</span>
            <span className="token-audit__value">{(audit.total_ticket_tokens || 0).toLocaleString()}</span>
          </div>

          {audit.tokens_by_project && audit.tokens_by_project.length > 0 && (
            <div className="token-audit__section">
              <div className="token-audit__section-title">by project</div>
              {audit.tokens_by_project
                .filter((p) => !demoProjectIds.has(p.project_id))
                .map((p, i) => (
                <div key={i} className="token-audit__row">
                  <span className="token-audit__label">{p.prefix || p.project_name || `project ${p.project_id}`}</span>
                  <span className="token-audit__value">
                    {(p.ticket_tokens || 0).toLocaleString()} tickets
                    {p.overhead_tokens != null && ` + ${p.overhead_tokens.toLocaleString()} overhead`}
                  </span>
                </div>
              ))}
            </div>
          )}

          {audit.tokens_by_agent && audit.tokens_by_agent.length > 0 && (
            <div className="token-audit__section">
              <div className="token-audit__section-title">by agent</div>
              {audit.tokens_by_agent
                .filter((a) => !demoAgentIds.has(a.agent_id))
                .map((a, i) => (
                <div key={i} className="token-audit__row">
                  <span className="token-audit__label">{agentNameMap[a.agent_id] || a.agent_name || `agent ${a.agent_id}`}</span>
                  <span className="token-audit__value">{(a.tokens || 0).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}

          {hasDiscrepancies && (
            <div className="token-audit__section">
              <div className="token-audit__section-title token-audit__section-title--error">discrepancies</div>
              {audit.discrepancies.map((d, i) => (
                <div key={i} className="token-audit__row token-audit__row--error">
                  <span className="token-audit__label">{d.description || d.message || JSON.stringify(d)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default TokenAudit;
