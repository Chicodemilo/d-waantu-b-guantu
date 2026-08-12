// Path: src/components/common/AuditViolations.jsx
// File: AuditViolations.jsx
// Created: 2026-08-12
// Purpose: Shared standards-audit findings block. Renders a labeled "Violations (N)" list of rule / severity / file:line / note, or "none" when clean. Promoted to common/ (DWB-031) so the ProjectPage StandardsAudits section and the AuditsPage render findings identically.
// Caller: components/project/StandardsAudits.jsx, pages/AuditsPage.jsx
// Callees: none
// Data In: props { violations } (array of { rule, severity, file, line, note })
// Data Out: default export AuditViolations component
// Last Modified: 2026-08-12 (DWB-031)

function fileLine(v) {
  if (!v.file) return '';
  return v.line != null ? `${v.file}:${v.line}` : v.file;
}

function AuditViolations({ violations }) {
  const items = Array.isArray(violations) ? violations : [];
  return (
    <div className="audit-block">
      <div className="audit-block__title">Violations ({items.length})</div>
      {items.length === 0 ? (
        <div className="audit-none">none</div>
      ) : (
        <ul className="audit-violations">
          {items.map((v, i) => (
            <li key={i} className="audit-violations__item">
              <span className="audit-violations__rule">{v.rule || 'rule'}</span>
              {v.severity && <span className="audit-violations__sev">{v.severity}</span>}
              {fileLine(v) && <span className="audit-violations__loc">{fileLine(v)}</span>}
              {v.note && <span className="audit-violations__note">{v.note}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default AuditViolations;
