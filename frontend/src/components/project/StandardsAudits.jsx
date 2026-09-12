// Path: src/components/project/StandardsAudits.jsx
// File: StandardsAudits.jsx
// Created: 2026-08-12
// Purpose: Render-only project-page section listing stored standards-audit scorecards. Each audit renders its verdict, branch/PR ref, run time, findings, and per-agent scorecard using the shared common/ audit pieces. Fetch + polling + loading/error state live in the useStandardsAudits hook.
// Caller: pages/ProjectPage.jsx
// Callees: hooks/useStandardsAudits, components/common/AuditVerdictBadge, components/common/AuditViolations, components/common/AuditScorecard
// Data In: projectId prop
// Data Out: Default export StandardsAudits component
// Last Modified: 2026-08-12 (DWB-031)

import useStandardsAudits from '../../hooks/useStandardsAudits';
import AuditVerdictBadge from '../common/AuditVerdictBadge';
import AuditViolations from '../common/AuditViolations';
import AuditScorecard from '../common/AuditScorecard';

function formatRunAt(iso) {
  if (!iso) return '-';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const t = new Date(ts);
  if (isNaN(t.getTime())) return '-';
  return t.toLocaleString();
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
      {audits.map((audit) => (
        <div key={audit.id} className="audit-card">
          <div className="audit-card__head">
            <AuditVerdictBadge verdict={audit.verdict} />
            <span className="audit-card__ref">{audit.pr_ref || audit.diff_range || '-'}</span>
            <span className="audit-card__time">{formatRunAt(audit.run_at)}</span>
            {audit.triggered_by && (
              <span className="audit-card__by">{audit.triggered_by}</span>
            )}
          </div>
          <AuditViolations violations={audit.violations} />
          <AuditScorecard scorecard={audit.scorecard} />
        </div>
      ))}
    </div>
  );
}

export default StandardsAudits;
