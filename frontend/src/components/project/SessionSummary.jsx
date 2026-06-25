// Path: src/components/project/SessionSummary.jsx
// File: SessionSummary.jsx
// Created: 2026-06-25
// Purpose: Session write-up block for the session detail page (DWB-486). Renders
//          the locked DWB-483 summary JSON: a one-line `lead` at top, a keyword
//          tag row (DWB-481 keywords[], sorted by weight desc), and each
//          summary.sections[] entry as an expandable CollapsibleSection whose body
//          is a reused SummaryHeader bullet list. Sections default open (the user
//          navigated here to read) and are individually collapsible. Graceful
//          empty state for legacy sessions where summary is null/empty.
// Caller: pages/SessionDetailPage.jsx
// Callees: react (useState), components/help/CollapsibleSection, components/help/SummaryHeader, styles/sessions.css
// Data In: summary ({ lead, sections: [{ title, bullets }] } | null), keywords ([{ keyword, weight }] | undefined)
// Data Out: default export SessionSummary component
// Last Modified: 2026-06-25

import { useState } from 'react';
import CollapsibleSection from '../help/CollapsibleSection';
import SummaryHeader from '../help/SummaryHeader';
import '../../styles/sessions.css';

function SessionSummary({ summary, keywords }) {
  // Track which sections the user has collapsed; default is open.
  const [closed, setClosed] = useState(() => new Set());

  const lead = summary && typeof summary.lead === 'string' ? summary.lead : '';
  const sections =
    summary && Array.isArray(summary.sections) ? summary.sections : [];
  const tags = (Array.isArray(keywords) ? keywords : [])
    .filter((k) => k && k.keyword)
    .slice()
    .sort((a, b) => (Number(b.weight) || 0) - (Number(a.weight) || 0));

  const hasContent = Boolean(lead) || sections.length > 0 || tags.length > 0;

  if (!hasContent) {
    return (
      <div
        className="session-summary session-summary--empty"
        data-testid="session-summary-empty"
      >
        No write-up recorded for this session.
      </div>
    );
  }

  const isOpen = (key) => !closed.has(key);
  const toggle = (key) =>
    setClosed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="session-summary" data-testid="session-summary">
      {lead && <p className="session-summary__lead">{lead}</p>}

      {tags.length > 0 && (
        <div className="session-summary__keywords" data-testid="session-summary-keywords">
          {tags.map((k, i) => (
            <span
              key={`${k.keyword}-${i}`}
              className="session-summary__tag"
              title={k.weight != null ? `weight ${k.weight}` : undefined}
            >
              {k.keyword}
            </span>
          ))}
        </div>
      )}

      {sections.map((s, idx) => {
        const key = `${idx}-${s.title}`;
        const bullets = Array.isArray(s.bullets) ? s.bullets : [];
        return (
          <CollapsibleSection
            key={key}
            title={s.title}
            open={isOpen(key)}
            onToggle={() => toggle(key)}
          >
            <SummaryHeader bullets={bullets} />
          </CollapsibleSection>
        );
      })}
    </div>
  );
}

export default SessionSummary;
