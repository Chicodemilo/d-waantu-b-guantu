// Path: src/utils/__tests__/nodeKinds.test.js
// File: nodeKinds.test.js
// Created: 2026-09-15
// Purpose: Tests for the pure pointer-kind helpers (DWB-542): kinds present in display order with docs label and per-node counts, unknown kinds appended by name, and the visibility rule (null = all, empty set = none, otherwise at least one pointer of a selected kind).
// Caller: vitest test runner
// Callees: ../nodeKinds
// Data In: Synthetic NodeRead fixtures
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect } from 'vitest';
import { pointerKinds, nodeHasSelectedKind, kindLabel } from '../nodeKinds';

const P = (kind) => ({ id: Math.random(), kind, ref: 'r', sha: 's', line_start: 1, line_end: 1 });
const N = (id, ...kinds) => ({ id, tag: `t${id}`, weight: 10, pointers: kinds.map(P) });

describe('nodeKinds (DWB-542)', () => {
  it('lists present kinds in display order with labels and node counts (a node counts once per kind)', () => {
    const nodes = [N(1, 'memory', 'code', 'code'), N(2, 'doc'), N(3, 'code', 'doc'), N(4, 'session')];
    expect(pointerKinds(nodes)).toEqual([
      { kind: 'code', label: 'code', count: 2 },
      { kind: 'doc', label: 'docs', count: 2 },
      { kind: 'memory', label: 'memory', count: 1 },
      { kind: 'session', label: 'session', count: 1 },
    ]);
    expect(pointerKinds([])).toEqual([]);
    expect(kindLabel('doc')).toBe('docs');
    expect(kindLabel('ticket')).toBe('ticket');
  });

  it('omits kinds not present and appends unknown kinds alphabetically after the known order', () => {
    const nodes = [N(1, 'zeta'), N(2, 'alpha'), N(3, 'memory')];
    expect(pointerKinds(nodes).map((k) => k.kind)).toEqual(['memory', 'alpha', 'zeta']);
  });

  it('nodeHasSelectedKind: null passes everything, empty set nothing, otherwise any selected pointer kind', () => {
    const codeDoc = N(1, 'code', 'doc');
    const memOnly = N(2, 'memory');
    expect(nodeHasSelectedKind(codeDoc, null)).toBe(true);
    expect(nodeHasSelectedKind(codeDoc, new Set())).toBe(false);
    expect(nodeHasSelectedKind(codeDoc, new Set(['memory']))).toBe(false);
    expect(nodeHasSelectedKind(codeDoc, new Set(['doc']))).toBe(true);
    expect(nodeHasSelectedKind(memOnly, new Set(['code', 'doc']))).toBe(false);
    expect(nodeHasSelectedKind({ id: 9, pointers: [] }, new Set(['code']))).toBe(false);
  });
});
