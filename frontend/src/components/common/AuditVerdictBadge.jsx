// Path: src/components/common/AuditVerdictBadge.jsx
// File: AuditVerdictBadge.jsx
// Created: 2026-08-12
// Purpose: Shared standards-audit verdict badge. Renders PASS (green) or REJECT (orange) as plain text per theme.css. Promoted to common/ (DWB-031) so the ProjectPage StandardsAudits section and the AuditsPage both render verdicts identically.
// Caller: components/project/StandardsAudits.jsx, pages/AuditsPage.jsx
// Callees: none
// Data In: props { verdict } (string, "pass" or "reject", any case)
// Data Out: default export AuditVerdictBadge component
// Last Modified: 2026-08-12 (DWB-031)

function AuditVerdictBadge({ verdict }) {
  const v = (verdict || '').toLowerCase();
  return (
    <span className={`audit-verdict audit-verdict--${v}`}>
      {v === 'pass' ? 'PASS' : 'REJECT'}
    </span>
  );
}

export default AuditVerdictBadge;
