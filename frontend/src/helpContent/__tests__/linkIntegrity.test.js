// Path: src/helpContent/__tests__/linkIntegrity.test.js
// File: linkIntegrity.test.js
// Created: 2026-06-25
// Purpose: Link-integrity guard for the DWB-496 cross-link feature. Iterates
//          every authored help section in the REAL helpContent index and asserts
//          each optional links[] entry is valid: a section cross-link's `to`
//          resolves to a real canonical section key (the NAV_GROUPS vocabulary),
//          or a DWB-501 portal link's `route` is an in-app path. The HelpPage
//          render silently skips links whose target is unknown, so a typo'd / dead
//          target would vanish unnoticed without this test - it guards Freddie's
//          DWB-497 authoring, the DWB-501 portal links, and any future links from
//          rotting. DWB-501: portal links are further constrained to the five
//          global sections and the five known static routes.
// Caller: vitest test runner
// Callees: ../index (allSections, NAV_GROUPS via import.meta.glob)
// Data In: real authored section modules
// Data Out: test assertions
// Last Modified: 2026-06-25

import { describe, it, expect } from 'vitest';
import { allSections, NAV_GROUPS } from '../index';

// The canonical section vocabulary, derived from the single source of truth
// (NAV_GROUPS) rather than hand-copied, so it cannot drift from the index.
const CANONICAL_KEYS = new Set(NAV_GROUPS.flatMap((g) => g.keys));

describe('help cross-link integrity (DWB-496/497)', () => {
  it('exposes the expected canonical section vocabulary', () => {
    // Sanity: guard the vocabulary the link targets are validated against, so a
    // future NAV_GROUPS change that drops/renames a key is caught here too.
    expect([...CANONICAL_KEYS].sort()).toEqual(
      [
        'archie_channel',
        'comms',
        'dashboard',
        'docs',
        'error_log',
        'jira',
        'sessions',
        'system_docs',
        'system_tests',
        'team',
        'tests',
        'tickets',
      ].sort()
    );
  });

  it('every section cross-link.to resolves to a real canonical section key', () => {
    const bad = [];
    for (const section of allSections) {
      const links = Array.isArray(section.links) ? section.links : [];
      for (const link of links) {
        if (!link) {
          bad.push(`${section.key} -> ${link}`);
          continue;
        }
        // DWB-501: portal links target a route, not a section key; validated below.
        if (link.route) continue;
        if (!CANONICAL_KEYS.has(link.to)) {
          bad.push(`${section.key} -> ${JSON.stringify(link.to)}`);
        }
      }
    }
    // Message lists every offending link so a typo is obvious in the failure.
    expect(bad).toEqual([]);
  });

  it('every link carries a non-empty label and exactly one target (to or route)', () => {
    const malformed = [];
    for (const section of allSections) {
      const links = Array.isArray(section.links) ? section.links : [];
      for (const link of links) {
        const okLabel =
          typeof link?.label === 'string' && link.label.trim().length > 0;
        const okTo = typeof link?.to === 'string' && link.to.length > 0;
        // DWB-501: portal links use an in-app route path instead of `to`.
        const okRoute =
          typeof link?.route === 'string' && link.route.startsWith('/');
        // Exactly one of to / route, plus a label.
        if (!okLabel || okTo === okRoute) {
          malformed.push(`${section.key} -> ${JSON.stringify(link)}`);
        }
      }
    }
    expect(malformed).toEqual([]);
  });

  it('DWB-501: portal links appear only on global sections and target a known global route', () => {
    // Global sections (the Overview group) are the only ones whose routes are
    // static; project-scoped sections live under /projects/:id and the help page
    // has no current-project context, so portal links there would be broken.
    // Derived from NAV_GROUPS so it cannot drift from the index.
    const overview = NAV_GROUPS.find((g) => g.id === 'overview');
    const GLOBAL_SECTION_KEYS = new Set(overview ? overview.keys : []);
    const KNOWN_GLOBAL_ROUTES = new Set([
      '/',
      '/tests',
      '/docs',
      '/errors',
      '/archie-channel',
    ]);

    const violations = [];
    for (const section of allSections) {
      const links = Array.isArray(section.links) ? section.links : [];
      for (const link of links) {
        if (!link || !link.route) continue; // section links validated above
        if (!GLOBAL_SECTION_KEYS.has(section.key)) {
          violations.push(
            `portal link on non-global section ${section.key} -> ${link.route}`
          );
        }
        if (!KNOWN_GLOBAL_ROUTES.has(link.route)) {
          violations.push(`${section.key} -> unknown route ${JSON.stringify(link.route)}`);
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it('no section cross-links to itself', () => {
    const selfLinks = [];
    for (const section of allSections) {
      const links = Array.isArray(section.links) ? section.links : [];
      for (const link of links) {
        if (link && link.to === section.key) {
          selfLinks.push(section.key);
        }
      }
    }
    expect(selfLinks).toEqual([]);
  });
});
