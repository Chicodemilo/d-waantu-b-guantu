// Path: src/utils/__tests__/nodeScale.test.js
// File: nodeScale.test.js
// Created: 2026-09-15
// Purpose: Tests for the pure log-bucket node scaler (DWB-534): bounds, monotonicity, flat-set fallback, and the live project-1 weight profile (min 10, max 121, top-20 all >= 113) landing the whole top-20 in the single cap bucket so no node dwarfs the page.
// Caller: vitest test runner
// Callees: ../nodeScale
// Data In: Synthetic weight sets
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect } from 'vitest';
import { bucketForWeight, scaleNodes, weightBounds, NODE_SCALE_BUCKETS } from '../nodeScale';

// Live top-20 weights from GET /api/projects/1/nodes on 2026-09-15.
const LIVE_TOP20 = [121, 121, 119, 119, 118, 118, 118, 118, 118, 117, 117, 116, 116, 115, 115, 114, 114, 113, 113, 113];

describe('nodeScale (DWB-534)', () => {
  it('maps min to bucket 0 and max to the top bucket', () => {
    expect(bucketForWeight(10, 10, 121)).toBe(0);
    expect(bucketForWeight(121, 10, 121)).toBe(NODE_SCALE_BUCKETS - 1);
  });

  it('is monotonic non-decreasing in weight and clamps out-of-range values', () => {
    let prev = -1;
    for (let w = 10; w <= 121; w++) {
      const b = bucketForWeight(w, 10, 121);
      expect(b).toBeGreaterThanOrEqual(prev);
      expect(b).toBeGreaterThanOrEqual(0);
      expect(b).toBeLessThanOrEqual(NODE_SCALE_BUCKETS - 1);
      prev = b;
    }
    expect(bucketForWeight(1, 10, 121)).toBe(0);
    expect(bucketForWeight(9999, 10, 121)).toBe(NODE_SCALE_BUCKETS - 1);
  });

  it('is log-spaced: the median live weight (25) sits in the lower-middle, not near the top', () => {
    const b = bucketForWeight(25, 10, 121);
    expect(b).toBeGreaterThanOrEqual(2);
    expect(b).toBeLessThanOrEqual(3);
  });

  it('puts the whole live top-20 in the single cap bucket (top nodes do not dwarf the page)', () => {
    const buckets = new Set(LIVE_TOP20.map((w) => bucketForWeight(w, 10, 121)));
    expect(buckets.size).toBe(1);
    expect([...buckets][0]).toBe(NODE_SCALE_BUCKETS - 1);
  });

  it('falls back to the middle bucket for a flat set or a single node', () => {
    const mid = Math.floor((NODE_SCALE_BUCKETS - 1) / 2);
    expect(bucketForWeight(40, 40, 40)).toBe(mid);
    expect(scaleNodes([{ id: 1, weight: 40 }])[0].bucket).toBe(mid);
  });

  it('scaleNodes decorates a copy with bucket, re-fitting bounds to the set given', () => {
    const nodes = [{ id: 1, weight: 10 }, { id: 2, weight: 30 }, { id: 3, weight: 121 }];
    const scaled = scaleNodes(nodes);
    expect(scaled).not.toBe(nodes);
    expect(scaled[0].bucket).toBe(0);
    expect(scaled[2].bucket).toBe(NODE_SCALE_BUCKETS - 1);
    expect(nodes[0].bucket).toBeUndefined();
    // A limited subset re-fits: 30 becomes the new max.
    expect(scaleNodes(nodes.slice(0, 2))[1].bucket).toBe(NODE_SCALE_BUCKETS - 1);
    expect(weightBounds([])).toEqual({ minW: 0, maxW: 0 });
    expect(scaleNodes([])).toEqual([]);
  });
});
