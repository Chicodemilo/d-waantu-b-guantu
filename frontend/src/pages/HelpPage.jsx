// Path: src/pages/HelpPage.jsx
// File: HelpPage.jsx
// Created: 2026-06-25
// Purpose: Help Center page (DWB-469). Top region is the QUICK START: a linear
//          ordered startup flow and standalone callouts, rendered as two visually
//          separate blocks (not chained). Below, domain CollapsibleSections mirror
//          the sidebar nav and are driven by helpContent/index.js, so content lands
//          incrementally. A FuzzySearch at the top filters the domain sections live
//          and force-opens matches.
// Caller: App.jsx route /help
// Callees: react (useState, useMemo), components/help/FuzzySearch, CollapsibleSection,
//          SummaryHeader; hooks/useFuzzyFilter; helpContent (helpGroups, quickStart)
// Data In: static help content from helpContent/index.js
// Data Out: default export HelpPage component
// Last Modified: 2026-06-25

import { useState, useMemo } from 'react';
import FuzzySearch from '../components/help/FuzzySearch';
import CollapsibleSection from '../components/help/CollapsibleSection';
import SummaryHeader from '../components/help/SummaryHeader';
import useFuzzyFilter from '../hooks/useFuzzyFilter';
import { helpGroups, quickStart } from '../helpContent';
import '../styles/help.css';

// Build the searchable text for a section: title + summary + bullets, so the
// fuzzy matcher hits content, not just headings.
function sectionSearchText(section) {
  const s = section.summary || {};
  return [section.title, s.why, s.how, s.where, ...(section.bullets || [])]
    .filter(Boolean)
    .join(' ');
}

function HelpPage() {
  const [query, setQuery] = useState('');
  const [manualOpen, setManualOpen] = useState(() => new Set());

  const allSections = useMemo(
    () => helpGroups.flatMap((g) => g.sections),
    []
  );
  const searchItems = useMemo(
    () => allSections.map((s) => ({ id: s.key, text: sectionSearchText(s) })),
    [allSections]
  );

  const { matchedIds } = useFuzzyFilter(searchItems, query);
  const querying = query.trim() !== '';

  // When searching, show only matching sections and force them open. Otherwise
  // show everything, opened only by the user's manual toggles.
  const visibleGroups = useMemo(() => {
    if (!querying) return helpGroups;
    return helpGroups
      .map((g) => ({
        ...g,
        sections: g.sections.filter((s) => matchedIds.has(s.key)),
      }))
      .filter((g) => g.sections.length > 0);
  }, [querying, matchedIds]);

  const visibleCount = querying
    ? visibleGroups.reduce((n, g) => n + g.sections.length, 0)
    : allSections.length;

  const isOpen = (key) =>
    querying ? matchedIds.has(key) : manualOpen.has(key);

  const toggle = (key) => {
    setManualOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const flow = (quickStart && quickStart.flow) || [];
  const callouts = (quickStart && quickStart.callouts) || [];

  return (
    <div className="help-page">
      <header className="help-page__header">
        <h1 className="help-page__title">Help</h1>
        <p className="help-page__lead">
          How D'Waantu B'Guantu works: start here, then dig into any view.
        </p>
      </header>

      {/* QUICK START: two visually separate regions, not chained together. */}
      <section className="help-quickstart">
        <h2 className="help-quickstart__title">Quick start</h2>
        <div className="help-quickstart__regions">
          <div className="help-flow">
            <h3 className="help-flow__title">Startup flow</h3>
            {flow.length > 0 ? (
              <ol className="help-flow__list">
                {flow.map((step, i) => (
                  <li key={i} className="help-flow__step">
                    <span className="help-flow__step-title">{step.title}</span>
                    {step.detail && (
                      <span className="help-flow__step-detail">{step.detail}</span>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="help-empty">Quick-start flow coming soon.</p>
            )}
          </div>

          <div className="help-callouts">
            <h3 className="help-callouts__title">Shortcuts</h3>
            {callouts.length > 0 ? (
              <div className="help-callouts__grid">
                {callouts.map((c, i) => (
                  <div key={i} className="help-callout">
                    <span className="help-callout__title">{c.title}</span>
                    {c.detail && (
                      <span className="help-callout__detail">{c.detail}</span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="help-empty">Shortcuts coming soon.</p>
            )}
          </div>
        </div>
      </section>

      {/* DOMAIN SECTIONS: mirror the nav, filtered + force-opened by search. */}
      <section className="help-domains">
        <div className="help-domains__search">
          <FuzzySearch
            value={query}
            onChange={setQuery}
            placeholder="filter help topics..."
            label="search help"
            resultCount={querying ? visibleCount : null}
            totalCount={allSections.length}
          />
        </div>

        {visibleGroups.length === 0 ? (
          <p className="help-empty">No topics match "{query}".</p>
        ) : (
          visibleGroups.map((group) => (
            <div key={group.id} className="help-group">
              <h2 className="help-group__label">{group.label}</h2>
              {group.sections.map((section) => (
                <CollapsibleSection
                  key={section.key}
                  title={section.title}
                  open={isOpen(section.key)}
                  onToggle={() => toggle(section.key)}
                >
                  <SummaryHeader
                    why={section.summary && section.summary.why}
                    how={section.summary && section.summary.how}
                    where={section.summary && section.summary.where}
                    bullets={section.bullets}
                  />
                </CollapsibleSection>
              ))}
            </div>
          ))
        )}
      </section>
    </div>
  );
}

export default HelpPage;
