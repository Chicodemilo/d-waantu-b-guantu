// Path: src/components/common/AuditScorecard.jsx
// File: AuditScorecard.jsx
// Created: 2026-08-12
// Purpose: Shared standards-audit scorecard block. Renders a labeled "Scorecard (N)" list of per-agent sticks/carrots (agent, signed delta, reason), or "none" when empty. Promoted to common/ (DWB-031) so the ProjectPage StandardsAudits section and the AuditsPage render scorecards identically.
// Caller: components/project/StandardsAudits.jsx, pages/AuditsPage.jsx
// Callees: none
// Data In: props { scorecard } (array of { agent, delta, reason })
// Data Out: default export AuditScorecard component
// Last Modified: 2026-08-12 (DWB-031)

function formatDelta(delta) {
  const n = Number(delta) || 0;
  return n > 0 ? `+${n}` : `${n}`;
}

function deltaClass(delta) {
  const n = Number(delta) || 0;
  if (n > 0) return ' audit-scorecard__delta--up';
  if (n < 0) return ' audit-scorecard__delta--down';
  return '';
}

function AuditScorecard({ scorecard }) {
  const items = Array.isArray(scorecard) ? scorecard : [];
  return (
    <div className="audit-block">
      <div className="audit-block__title">Scorecard ({items.length})</div>
      {items.length === 0 ? (
        <div className="audit-none">none</div>
      ) : (
        <ul className="audit-scorecard">
          {items.map((s, i) => (
            <li key={i} className="audit-scorecard__item">
              <span className="audit-scorecard__agent">{s.agent}</span>
              <span className={`audit-scorecard__delta${deltaClass(s.delta)}`}>
                {formatDelta(s.delta)}
              </span>
              <span className="audit-scorecard__reason">{s.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default AuditScorecard;
