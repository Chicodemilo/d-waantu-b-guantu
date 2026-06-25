// Path: src/components/help/SummaryHeader.jsx
// File: SummaryHeader.jsx
// Created: 2026-06-25
// Purpose: Generic Why / How / Where summary block plus a bullet list (DWB-468).
//          Pure presentational; renders only the fields it is given (any of why,
//          how, where may be omitted). Used as the head of each help domain section.
// Caller: pages/HelpPage.jsx + helpContent/* section renderers
// Callees: none
// Data In: why (node), how (node), where (node), bullets (string[]|node[])
// Data Out: default export SummaryHeader component
// Last Modified: 2026-06-25

import '../../styles/help.css';

function Row({ label, children }) {
  if (!children) return null;
  return (
    <div className="summary-header__row">
      <span className="summary-header__label">{label}</span>
      <span className="summary-header__text">{children}</span>
    </div>
  );
}

function SummaryHeader({ why, how, where, bullets }) {
  const list = Array.isArray(bullets) ? bullets.filter(Boolean) : [];

  return (
    <div className="summary-header">
      <Row label="Why">{why}</Row>
      <Row label="How">{how}</Row>
      <Row label="Where">{where}</Row>
      {list.length > 0 && (
        <ul className="summary-header__bullets">
          {list.map((b, i) => (
            <li key={i} className="summary-header__bullet">
              {b}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default SummaryHeader;
