// Path: src/pages/HelpPage.jsx
// File: HelpPage.jsx
// Created: 2026-06-25
// Purpose: Help Center page (DWB-469, DWB-496). The whole page is uniformly
//          collapsible. The QUICK START (linear startup flow + standalone callouts,
//          two visually separate blocks) is itself a CollapsibleSection that defaults
//          OPEN. Below, domain CollapsibleSections mirror the sidebar nav and are
//          driven by helpContent/index.js, so content lands incrementally. A
//          FuzzySearch filters the domain sections live and force-opens matches.
//          Sections may declare cross-links ({to, label}) that force-open AND scroll
//          a target section into view (DWB-496), reusing the same force-open plumbing.
// Caller: App.jsx route /help
// Callees: react (useState, useMemo, useEffect), components/help/FuzzySearch, CollapsibleSection,
//          SummaryHeader; hooks/useFuzzyFilter; helpContent (helpGroups, quickStart)
// Data In: static help content from helpContent/index.js
// Data Out: default export HelpPage component
// Last Modified: 2026-06-25

import { useState, useMemo, useEffect } from 'react';
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

// DWB-496: DOM id for a domain section, so a cross-link can scroll it into view.
const sectionDomId = (key) => `help-section-${key}`;

function HelpPage() {
  const [query, setQuery] = useState('');
  const [manualOpen, setManualOpen] = useState(() => new Set());
  // DWB-496: quick-start is collapsible too, but starts OPEN (first thing a
  // newcomer reads).
  const [quickStartOpen, setQuickStartOpen] = useState(true);
  // DWB-496: a section key queued to scroll into view after the open-state commit.
  const [pendingScroll, setPendingScroll] = useState(null);

  const allSections = useMemo(
    () => helpGroups.flatMap((g) => g.sections),
    []
  );
  const sectionKeys = useMemo(
    () => new Set(allSections.map((s) => s.key)),
    [allSections]
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

  // DWB-496: cross-link navigation. Clear any active filter (so the target is
  // visible regardless of the current search), force the target section open,
  // and queue it to scroll into view once the open-state commit lands.
  const goToSection = (key) => {
    if (!sectionKeys.has(key)) return;
    setQuery('');
    setManualOpen((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    setPendingScroll(key);
  };

  useEffect(() => {
    if (!pendingScroll) return;
    const el =
      typeof document !== 'undefined'
        ? document.getElementById(sectionDomId(pendingScroll))
        : null;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    setPendingScroll(null);
  }, [pendingScroll]);

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

      {/* QUICK START: collapsible (default open), two visually separate regions. */}
      <CollapsibleSection
        title="Quick start"
        open={quickStartOpen}
        onToggle={setQuickStartOpen}
        className="help-quickstart"
      >
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
      </CollapsibleSection>

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
              {group.sections.map((section) => {
                // DWB-496: only render cross-links whose target section exists.
                const links = (Array.isArray(section.links) ? section.links : [])
                  .filter((l) => l && sectionKeys.has(l.to));
                return (
                  <CollapsibleSection
                    key={section.key}
                    id={sectionDomId(section.key)}
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
                    {links.length > 0 && (
                      <div className="help-section__links">
                        <span className="help-section__links-label">See also</span>
                        {links.map((l) => (
                          <button
                            key={l.to}
                            type="button"
                            className="help-link"
                            onClick={() => goToSection(l.to)}
                          >
                            {l.label || l.to}
                          </button>
                        ))}
                      </div>
                    )}
                  </CollapsibleSection>
                );
              })}
            </div>
          ))
        )}
      </section>
    </div>
  );
}

export default HelpPage;
