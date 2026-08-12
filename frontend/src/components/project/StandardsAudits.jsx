// Path: src/components/project/StandardsAudits.jsx
// File: StandardsAudits.jsx
// Created: 2026-08-12
// Purpose: Render-only project-page section listing stored standards-audit scorecards. Each audit renders its verdict (PASS/REJECT, plain text), branch/PR ref, run time, violations (rule + file:line + note), and the per-agent scorecard (agent, delta, reason). Fetch + polling + loading/error state live in the useStandardsAudits hook.
// Caller: pages/ProjectPage.jsx
// Callees: hooks/useStandardsAudits
// Data In: projectId prop
// Data Out: Default export StandardsAudits component
// Last Modified: 2026-08-12 (DWB-018)

import useStandardsAudits from '../../hooks/useStandardsAudits';

function formatRunAt(iso) {
  if (!iso) return '-';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const t = new Date(ts);
  if (isNaN(t.getTime())) return '-';
  return t.toLocaleString();
}

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

function fileLine(v) {
  if (!v.file) return '';
  return v.line != null ? `${v.file}:${v.line}` : v.file;
}

function StandardsAudits({ projectId }) {
  const { audits, loading, error } = useStandardsAudits(projectId);

  if (loading) {
    return (
      <div className="audits">
        <div className="audits__empty">Loading audits...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="audits">
        <div className="audits__empty audits__empty--error">Could not load audits</div>
      </div>
    );
  }

  if (audits.length === 0) {
    return (
      <div className="audits">
        <div className="audits__empty">No audits yet</div>
      </div>
    );
  }

  return (
    <div className="audits">
      {audits.map((audit) => {
        const verdict = (audit.verdict || '').toLowerCase();
        const violations = Array.isArray(audit.violations) ? audit.violations : [];
        const scorecard = Array.isArray(audit.scorecard) ? audit.scorecard : [];

        return (
          <div key={audit.id} className="audit-card">
            <div className="audit-card__head">
              <span className={`audit-card__verdict audit-card__verdict--${verdict}`}>
                {verdict === 'pass' ? 'PASS' : 'REJECT'}
              </span>
              <span className="audit-card__ref">{audit.pr_ref || '-'}</span>
              {audit.diff_range && (
                <span className="audit-card__range">{audit.diff_range}</span>
              )}
              <span className="audit-card__time">{formatRunAt(audit.run_at)}</span>
              {audit.triggered_by && (
                <span className="audit-card__by">{audit.triggered_by}</span>
              )}
            </div>

            <div className="audit-card__block">
              <div className="audit-card__block-title">
                Violations ({violations.length})
              </div>
              {violations.length === 0 ? (
                <div className="audit-card__none">none</div>
              ) : (
                <ul className="audit-violations">
                  {violations.map((v, i) => (
                    <li key={i} className="audit-violations__item">
                      <span className="audit-violations__rule">{v.rule || 'rule'}</span>
                      {v.severity && (
                        <span className="audit-violations__sev">{v.severity}</span>
                      )}
                      {fileLine(v) && (
                        <span className="audit-violations__loc">{fileLine(v)}</span>
                      )}
                      {v.note && (
                        <span className="audit-violations__note">{v.note}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="audit-card__block">
              <div className="audit-card__block-title">
                Scorecard ({scorecard.length})
              </div>
              {scorecard.length === 0 ? (
                <div className="audit-card__none">none</div>
              ) : (
                <ul className="audit-scorecard">
                  {scorecard.map((s, i) => (
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
          </div>
        );
      })}
    </div>
  );
}

export default StandardsAudits;
