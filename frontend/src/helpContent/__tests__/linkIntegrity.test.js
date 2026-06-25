// Path: src/helpContent/__tests__/linkIntegrity.test.js
// File: linkIntegrity.test.js
// Created: 2026-06-25
// Purpose: Link-integrity guard for the DWB-496 cross-link feature. Iterates
//          every authored help section in the REAL helpContent index and asserts
//          each optional links[].to resolves to a real canonical section key
//          (the NAV_GROUPS vocabulary). The HelpPage render silently skips
//          cross-links whose target is unknown, so a typo'd / dead `to` would
//          vanish unnoticed without this test - it guards Freddie's DWB-497
//          authoring and any future links from rotting.
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

  it('every section link.to resolves to a real canonical section key', () => {
    const bad = [];
    for (const section of allSections) {
      const links = Array.isArray(section.links) ? section.links : [];
      for (const link of links) {
        if (!link || !CANONICAL_KEYS.has(link.to)) {
          bad.push(`${section.key} -> ${link ? JSON.stringify(link.to) : link}`);
        }
      }
    }
    // Message lists every offending link so a typo is obvious in the failure.
    expect(bad).toEqual([]);
  });

  it('every section link carries a non-empty label and a to', () => {
    const malformed = [];
    for (const section of allSections) {
      const links = Array.isArray(section.links) ? section.links : [];
      for (const link of links) {
        const okTo = typeof link?.to === 'string' && link.to.length > 0;
        const okLabel =
          typeof link?.label === 'string' && link.label.trim().length > 0;
        if (!okTo || !okLabel) {
          malformed.push(`${section.key} -> ${JSON.stringify(link)}`);
        }
      }
    }
    expect(malformed).toEqual([]);
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
