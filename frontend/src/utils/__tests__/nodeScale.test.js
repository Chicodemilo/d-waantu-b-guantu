// Path: src/utils/__tests__/nodeScale.test.js
// File: nodeScale.test.js
// Created: 2026-09-15
// Purpose: Tests for the pure log-bucket node scaler (DWB-534): bounds, monotonicity, flat-set fallback, and the live project-1 weight profile (min 10, max 121, top-20 all >= 113) landing the whole top-20 in the single cap bucket so no node dwarfs the page. DWB-541: headliner tier = exactly ceil(2% of N) ids (minimum 1), highest weights first, ties by input order, pinned when scaling a subset.
// Caller: vitest test runner
// Callees: ../nodeScale
// Data In: Synthetic weight sets
// Data Out: Test assertions
// Last Modified: 2026-09-15 (DWB-541)

import { describe, it, expect } from 'vitest';
import { bucketForWeight, scaleNodes, weightBounds, headlinerCount, headlinerIds, NODE_SCALE_BUCKETS, HEADLINER_BUCKET } from '../nodeScale';

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
    // a single node is its own headliner (DWB-541); with the tier pinned empty it falls to the middle bucket
    expect(scaleNodes([{ id: 1, weight: 40 }])[0].bucket).toBe(HEADLINER_BUCKET);
    expect(scaleNodes([{ id: 1, weight: 40 }], undefined, new Set())[0].bucket).toBe(mid);
  });

  it('scaleNodes decorates a copy with bucket, re-fitting bounds to the set given', () => {
    const nodes = [{ id: 1, weight: 10 }, { id: 2, weight: 30 }, { id: 3, weight: 121 }];
    // pin the headliner tier empty here to test the log fit alone
    const none = new Set();
    const scaled = scaleNodes(nodes, undefined, none);
    expect(scaled).not.toBe(nodes);
    expect(scaled[0].bucket).toBe(0);
    expect(scaled[2].bucket).toBe(NODE_SCALE_BUCKETS - 1);
    expect(nodes[0].bucket).toBeUndefined();
    // without a pinned set the heaviest node is the headliner
    expect(scaleNodes(nodes)[2].bucket).toBe(HEADLINER_BUCKET);
    // A limited subset re-fits: 30 becomes the new max.
    expect(scaleNodes(nodes.slice(0, 2), undefined, none)[1].bucket).toBe(NODE_SCALE_BUCKETS - 1);
    expect(weightBounds([])).toEqual({ minW: 0, maxW: 0 });
    expect(scaleNodes([])).toEqual([]);
  });

  describe('headliner tier (DWB-541)', () => {
    const mk = (n, weightOf) => Array.from({ length: n }, (_, i) => ({ id: i + 1, weight: weightOf(i) }));

    it('counts exactly ceil(2%) with a minimum of 1 and zero for an empty set', () => {
      expect(headlinerCount(0)).toBe(0);
      expect(headlinerCount(1)).toBe(1);
      expect(headlinerCount(6)).toBe(1);
      expect(headlinerCount(50)).toBe(1);
      expect(headlinerCount(51)).toBe(2);
      expect(headlinerCount(100)).toBe(2);
      expect(headlinerCount(3544)).toBe(71);
      expect(headlinerCount(3668)).toBe(74);
    });

    it('picks the highest weights, breaking ties by input order so the count is exact', () => {
      // 100 nodes, weights descending 121..22, so k = 2 -> ids 1 and 2
      const nodes = mk(100, (i) => 121 - i);
      expect([...headlinerIds(nodes)]).toEqual([1, 2]);
      // shuffled input still picks the two heaviest
      const shuffled = [...nodes].reverse();
      expect([...headlinerIds(shuffled)].sort()).toEqual([1, 2]);
      // tie at the cut: ids 1,2,3 all weight 121 -> first two in input order
      const tied = mk(100, (i) => (i < 3 ? 121 : 50));
      expect([...headlinerIds(tied)]).toEqual([1, 2]);
      expect(headlinerIds(tied).size).toBe(2);
      expect(headlinerIds([]).size).toBe(0);
    });

    it('scaleNodes puts headliners in HEADLINER_BUCKET (above b7) and leaves b0-b7 for the rest', () => {
      const nodes = mk(100, (i) => 121 - i);
      const scaled = scaleNodes(nodes);
      expect(HEADLINER_BUCKET).toBe(NODE_SCALE_BUCKETS);
      expect(scaled[0].bucket).toBe(HEADLINER_BUCKET);
      expect(scaled[1].bucket).toBe(HEADLINER_BUCKET);
      expect(scaled[2].bucket).toBe(NODE_SCALE_BUCKETS - 1);
      expect(scaled.filter((n) => n.bucket === HEADLINER_BUCKET)).toHaveLength(2);
      expect(Math.max(...scaled.slice(2).map((n) => n.bucket))).toBe(NODE_SCALE_BUCKETS - 1);
      // a single node is its own headliner
      expect(scaleNodes([{ id: 9, weight: 40 }])[0].bucket).toBe(HEADLINER_BUCKET);
    });

    it('a pinned headliner set from the full set survives scaling a subset', () => {
      const full = mk(100, (i) => 121 - i);
      const pinned = headlinerIds(full);
      // subset without any headliner: none promoted when pinned, one derived when not
      const subset = full.slice(10, 20);
      expect(scaleNodes(subset, undefined, pinned).some((n) => n.bucket === HEADLINER_BUCKET)).toBe(false);
      expect(scaleNodes(subset).filter((n) => n.bucket === HEADLINER_BUCKET)).toHaveLength(1);
      // subset containing headliner id 2 keeps it
      const withTop = [full[1], ...full.slice(50, 55)];
      const scaled = scaleNodes(withTop, undefined, pinned);
      expect(scaled[0].bucket).toBe(HEADLINER_BUCKET);
      expect(scaled.slice(1).every((n) => n.bucket < HEADLINER_BUCKET)).toBe(true);
    });
  });
});
