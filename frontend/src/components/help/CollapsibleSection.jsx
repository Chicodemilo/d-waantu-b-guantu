// Path: src/components/help/CollapsibleSection.jsx
// File: CollapsibleSection.jsx
// Created: 2026-06-25
// Purpose: Generic titled expand/collapse panel with a CONTROLLED open state (DWB-468).
//          The parent owns `open` so an external concern (e.g. fuzzy search) can
//          force-open matching sections. Plain-text caret only, no icons. Pure
//          presentational.
// Caller: pages/HelpPage.jsx (and any page needing controlled collapsible regions)
// Callees: none (controlled by parent via open/onToggle)
// Data In: title (node), open (bool), onToggle (fn), children (node), subtitle (node),
//          className (string), id (string - set on the section element so a parent
//          can scroll it into view, DWB-496)
// Data Out: default export CollapsibleSection; fires onToggle(!open) on header click
// Last Modified: 2026-06-25

import '../../styles/help.css';

function CollapsibleSection({
  title,
  open = false,
  onToggle,
  children,
  subtitle = null,
  className = '',
  id,
}) {
  const handleToggle = () => {
    if (onToggle) onToggle(!open);
  };

  return (
    <section id={id} className={`collapsible${open ? ' collapsible--open' : ''} ${className}`.trim()}>
      <button
        type="button"
        className="collapsible__header"
        onClick={handleToggle}
        aria-expanded={open}
      >
        <span className="collapsible__caret" aria-hidden="true">
          {open ? '[-]' : '[+]'}
        </span>
        <span className="collapsible__title">{title}</span>
        {subtitle && <span className="collapsible__subtitle">{subtitle}</span>}
      </button>
      {open && <div className="collapsible__body">{children}</div>}
    </section>
  );
}

export default CollapsibleSection;
