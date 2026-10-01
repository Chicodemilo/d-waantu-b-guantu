// Path: src/components/project/__tests__/memoryModeCopy.test.js
// File: memoryModeCopy.test.js
// Created: 2026-09-30
// Purpose: DWB-597 AC4 and AC2 - source-level guards over the whole memory-mode surface: zero icons and zero em dashes in the copy, and no modal or dialog anywhere. Both are checked by reading the source rather than assumed, and files are discovered by pattern so a component written later cannot skip a check by existing after the test.
// Caller: vitest test runner
// Callees: node:fs, node:path (reads the component sources)
// Data In: the .jsx sources under src/components/project matching the memory-mode surface
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-597: added the no-modal guard)

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const COMPONENT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');

// DWB-597 AC4 asks for a grep rather than an assumption. Reading the source is
// what makes this hold for copy nobody has written yet: the overlay lands in
// this same surface, and a file discovered by pattern cannot skip a check that
// a hand-listed file would.
const SURFACE = /^Memory.*\.jsx$/;

// Em dash, en dash, and the pictographic / dingbat / arrow ranges that cover
// what actually gets reached for as an icon. Deliberately NOT "all non-ASCII":
// a curly apostrophe is a typography choice, not an icon, and banning it here
// would make this test fire on something the rule does not forbid.
const BANNED = [
  ['em dash', /—/],
  ['en dash', /–/],
  ['emoji or pictograph', /[\u{1F300}-\u{1FAFF}]/u],
  ['dingbat', /[✀-➿]/],
  ['miscellaneous symbol', /[☀-⛿]/],
  ['arrow', /[←-⇿]/],
  ['bullet or star glyph', /[•★☆●○]/],
];

function surfaceFiles() {
  return readdirSync(COMPONENT_DIR).filter((f) => SURFACE.test(f));
}

describe('memory-mode surface copy (DWB-597 AC4)', () => {
  it('finds the components it is supposed to be checking', () => {
    // Without this, a rename silently turns every case below into a vacuous
    // pass over an empty list. A check that cannot fail is worse than none.
    const files = surfaceFiles();
    expect(files.length).toBeGreaterThan(0);
    expect(files).toContain('MemoryModeToggle.jsx');
    expect(files).toContain('MemoryTransitionOverlay.jsx');
  });

  it.each(BANNED)('contains no %s', (label, pattern) => {
    const offenders = surfaceFiles().filter((f) =>
      pattern.test(readFileSync(join(COMPONENT_DIR, f), 'utf8'))
    );
    expect(offenders).toEqual([]);
  });
});

// AC2 and a standing rule older than this ticket: inline text confirmation,
// never a modal. This is the SOURCE half of that guarantee. The overlay's own
// render-level assertion comes with the overlay; this one already covers it,
// and covers whatever lands in this surface next, which is the same reason
// the copy checks discover files rather than listing them.
//
// components/common/Overlay.jsx is the ONE sanctioned modal in this codebase.
// It is sanctioned elsewhere and banned here: a transition is a status, and a
// status that intercepts clicks hands back the outage this lane exists to
// remove.
const MODAL_MARKERS = [
  ['Overlay import', /from\s+['"][^'"]*\/Overlay['"]/],
  ['dialog role', /role=\s*['"{]?\s*['"]?(alert)?dialog/],
  ['<dialog> element', /<dialog[\s>]/],
  ['aria-modal attribute', /aria-modal/],
];

describe('memory-mode surface stays inline (DWB-597 AC2)', () => {
  it.each(MODAL_MARKERS)('contains no %s', (label, pattern) => {
    const offenders = surfaceFiles().filter((f) =>
      pattern.test(readFileSync(join(COMPONENT_DIR, f), 'utf8'))
    );
    expect(offenders).toEqual([]);
  });
});
