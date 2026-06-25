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
//          DWBG-009: also renders the TL-authored `narrative` (same JSON shape as
//          summary) below the deterministic summary, with an author/timestamp
//          provenance line. Graceful when narrative is null.
//          DWBG-015: the narrative (lead + bullets) is rendered through InlineMarkdown
//          so it reads like a VS Code session wrap-up — inline `code` -> code chips,
//          [text](url) + bare file/commit refs -> clickable links. The DETERMINISTIC
//          summary stays plain (rendered via SummaryHeader) by design.
// Caller: pages/SessionDetailPage.jsx
// Callees: react (useState), components/help/CollapsibleSection, components/help/SummaryHeader, components/project/InlineMarkdown, styles/sessions.css
// Data In: summary ({ lead, sections: [{ title, bullets }] } | null), keywords ([{ keyword, weight }] | undefined), narrative (same shape as summary | null), narrativeAuthor (string | null), narrativeGeneratedAt (ISO string | null), refResolver (optional fn(ref) -> href for bare file/commit refs in the narrative)
// Data Out: default export SessionSummary component
// Last Modified: 2026-06-25 (DWBG-015: rich narrative rendering via InlineMarkdown)

import { useState } from 'react';
import CollapsibleSection from '../help/CollapsibleSection';
import SummaryHeader from '../help/SummaryHeader';
import InlineMarkdown from './InlineMarkdown';
import '../../styles/sessions.css';

// Normalize a write-up JSON ({ lead, sections }) into safe primitives.
function readWriteup(w) {
  const lead = w && typeof w.lead === 'string' ? w.lead : '';
  const sections = w && Array.isArray(w.sections) ? w.sections : [];
  return { lead, sections };
}

function SessionSummary({
  summary,
  keywords,
  narrative,
  narrativeAuthor,
  narrativeGeneratedAt,
  refResolver,
}) {
  // Track which sections the user has collapsed; default is open.
  const [closed, setClosed] = useState(() => new Set());

  const { lead, sections } = readWriteup(summary);
  const { lead: narrLead, sections: narrSections } = readWriteup(narrative);
  const tags = (Array.isArray(keywords) ? keywords : [])
    .filter((k) => k && k.keyword)
    .slice()
    .sort((a, b) => (Number(b.weight) || 0) - (Number(a.weight) || 0));

  const hasNarrative = Boolean(narrLead) || narrSections.length > 0;
  const hasContent =
    Boolean(lead) || sections.length > 0 || tags.length > 0 || hasNarrative;

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

  // Deterministic summary sections: plain bullets via SummaryHeader (unchanged).
  const renderSections = (secs, keyPrefix) =>
    secs.map((s, idx) => {
      const key = `${keyPrefix}-${idx}-${s.title}`;
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
    });

  // DWBG-015: narrative sections render bullets through InlineMarkdown so code
  // chips and links come alive. Same collapsible chrome as the summary.
  const renderNarrativeSections = (secs, keyPrefix) =>
    secs.map((s, idx) => {
      const key = `${keyPrefix}-${idx}-${s.title}`;
      const bullets = (Array.isArray(s.bullets) ? s.bullets : []).filter(Boolean);
      return (
        <CollapsibleSection
          key={key}
          title={s.title}
          open={isOpen(key)}
          onToggle={() => toggle(key)}
        >
          {bullets.length > 0 && (
            <ul className="narrative-bullets">
              {bullets.map((b, i) => (
                <li className="narrative-bullet" key={`${key}-b${i}`}>
                  <InlineMarkdown
                    text={b}
                    linkResolver={refResolver}
                    keyBase={`${key}-b${i}`}
                  />
                </li>
              ))}
            </ul>
          )}
        </CollapsibleSection>
      );
    });

  // "authored by tl · 2026-06-25" — provenance for the narrative block.
  const provenance = [
    narrativeAuthor ? `authored by ${narrativeAuthor}` : null,
    narrativeGeneratedAt
      ? String(narrativeGeneratedAt).slice(0, 10)
      : null,
  ]
    .filter(Boolean)
    .join(' · ');

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

      {renderSections(sections, 'sum')}

      {hasNarrative && (
        <div className="session-summary__narrative" data-testid="session-summary-narrative">
          <div className="session-summary__narrative-head">
            <span className="session-summary__narrative-label">Narrative</span>
            {provenance && (
              <span className="session-summary__narrative-prov">{provenance}</span>
            )}
          </div>
          {narrLead && (
            <p className="session-summary__lead session-summary__lead--narrative">
              <InlineMarkdown text={narrLead} linkResolver={refResolver} keyBase="narr-lead" />
            </p>
          )}
          {renderNarrativeSections(narrSections, 'narr')}
        </div>
      )}
    </div>
  );
}

export default SessionSummary;
