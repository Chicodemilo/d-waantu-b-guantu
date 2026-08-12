// Path: src/pages/AuditsPage.jsx
// File: AuditsPage.jsx
// Created: 2026-08-12
// Purpose: Project-level Audits view (DWB-031). Top summary header with project basics and audit stats (total, pass/reject counts, pass/fail percent), then a table of audit rows (ref, date/time, verdict) that expand in place to show who ran it, the violations, and the per-agent scorecard. Reuses the useStandardsAudits hook and the shared common/ audit render pieces.
// Caller: App.jsx (route: /projects/:id/audits)
// Callees: react (useState), react-router-dom (useParams, Link), store/useStore, hooks/useStandardsAudits, components/common/AuditVerdictBadge, components/common/AuditViolations, components/common/AuditScorecard
// Data In: Route param (id), project from Zustand store, audits from the hook
// Data Out: Default export AuditsPage component
// Last Modified: 2026-08-12 (DWB-031)

import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import useStore from '../store/useStore';
import useStandardsAudits from '../hooks/useStandardsAudits';
import AuditVerdictBadge from '../components/common/AuditVerdictBadge';
import AuditViolations from '../components/common/AuditViolations';
import AuditScorecard from '../components/common/AuditScorecard';

function formatTime(iso) {
  if (!iso) return '-';
  const ts = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '-';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

// pr_ref labels a PR when present; some projects audit commits/ranges with no PR,
// so fall back to diff_range as the better label in that case.
function auditRef(audit) {
  return audit.pr_ref || audit.diff_range || '-';
}

function AuditsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.projects).find((p) => p.id === Number(id));
  const { audits, loading, error } = useStandardsAudits(id);
  const [expandedId, setExpandedId] = useState(null);

  if (!project) {
    return <div className="empty-state" data-testid="audits-page">Project not found</div>;
  }

  const total = audits.length;
  const passCount = audits.filter((a) => (a.verdict || '').toLowerCase() === 'pass').length;
  const rejectCount = audits.filter((a) => (a.verdict || '').toLowerCase() === 'reject').length;
  const passPct = total ? Math.round((passCount / total) * 100) : 0;
  const failPct = total ? Math.round((rejectCount / total) * 100) : 0;

  const toggle = (auditId) =>
    setExpandedId((prev) => (prev === auditId ? null : auditId));

  return (
    <div className="audits-page" data-testid="audits-page">
      <h1 className="page-title">{project.prefix} Audits</h1>

      <div className="audit-summary">
        <div className="audit-summary__meta">
          <span className="audit-summary__name">{project.name}</span>
          {project.repo_path && (
            <span className="audit-summary__repo">{project.repo_path}</span>
          )}
        </div>
        <div className="audit-summary__stats">
          <div className="audit-stat">
            <span className="audit-stat__value">{total}</span>
            <span className="audit-stat__label">audited</span>
          </div>
          <div className="audit-stat">
            <span className="audit-stat__value audit-stat__value--pass">{passCount}</span>
            <span className="audit-stat__label">pass</span>
          </div>
          <div className="audit-stat">
            <span className="audit-stat__value audit-stat__value--reject">{rejectCount}</span>
            <span className="audit-stat__label">reject</span>
          </div>
          <div className="audit-stat">
            <span className="audit-stat__value">{passPct}%</span>
            <span className="audit-stat__label">pass rate</span>
          </div>
          <div className="audit-stat">
            <span className="audit-stat__value">{failPct}%</span>
            <span className="audit-stat__label">fail rate</span>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="empty-state" data-testid="audits-loading">Loading audits...</div>
      ) : error ? (
        <div className="empty-state audits__empty--error" data-testid="audits-error">
          Could not load audits
        </div>
      ) : total === 0 ? (
        <div className="empty-state" data-testid="audits-empty">No audits yet</div>
      ) : (
        <div className="audit-table">
          <div className="audit-table__head">
            <span className="audit-table__col-ref">Ref</span>
            <span className="audit-table__col-time">When</span>
            <span className="audit-table__col-verdict">Verdict</span>
          </div>
          {audits.map((audit) => {
            const open = expandedId === audit.id;
            return (
              <div key={audit.id} className={`audit-table__group${open ? ' audit-table__group--open' : ''}`}>
                <button
                  type="button"
                  className="audit-table__row"
                  onClick={() => toggle(audit.id)}
                  aria-expanded={open}
                >
                  <span className="audit-table__col-ref">
                    <span className="audit-table__caret">{open ? 'v' : '>'}</span>
                    {auditRef(audit)}
                  </span>
                  <span className="audit-table__col-time">{formatTime(audit.run_at)}</span>
                  <span className="audit-table__col-verdict">
                    <AuditVerdictBadge verdict={audit.verdict} />
                  </span>
                </button>
                {open && (
                  <div className="audit-table__detail">
                    <div className="audit-detail__who">
                      Triggered by: {audit.triggered_by || 'unknown'}
                    </div>
                    <AuditViolations violations={audit.violations} />
                    <AuditScorecard scorecard={audit.scorecard} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="audits-page__back">
        <Link to={`/projects/${id}`}>&larr; Back to project</Link>
      </div>
    </div>
  );
}

export default AuditsPage;
