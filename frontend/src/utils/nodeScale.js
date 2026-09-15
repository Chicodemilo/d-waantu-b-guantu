// Path: src/utils/nodeScale.js
// File: nodeScale.js
// Created: 2026-09-15
// Purpose: Pure weight-to-size bucketing for the node cloud (DWB-534). Maps a node weight onto a small fixed number of log-spaced buckets so the top nodes share one cap size instead of dwarfing the page; the CSS assigns a font-size per bucket. Bucket boundaries derive from the min/max of the set passed in, so the scale re-fits when the cloud is limited by a search. DWB-541 adds the headliner tier: exactly ceil(0.5% of N) nodes (minimum 1; Miles tweak, was 2%), the highest weights with ties broken by input order, land in a ninth bucket above b7; the id set is computed over the FULL set so a limited cloud keeps its headliners.
// Caller: components/nodes/NodeCloud.jsx (scaleNodes, bucketForWeight, headlinerIds), pages/NodesPage.jsx (weightBounds, headlinerIds), utils/__tests__/nodeScale.test.js
// Callees: None (leaf utility module)
// Data In: node weight (number), weight bounds, node arrays [{weight, ...}]
// Data Out: bucket index 0..buckets-1 (HEADLINER_BUCKET = buckets for the top 0.5%); headliner id Set; nodes decorated with a bucket field
// Last Modified: 2026-09-15 (DWB-541 tweak: 0.5%)

export const NODE_SCALE_BUCKETS = 8;
// The tier above the top regular bucket; CSS class node-cloud__node--b8.
export const HEADLINER_BUCKET = NODE_SCALE_BUCKETS;
export const HEADLINER_SHARE = 0.005;

// How many headliners a set of n nodes has: ceil(0.5% of n), never fewer than 1 when n > 0.
export function headlinerCount(n, share = HEADLINER_SHARE) {
  if (!(n > 0)) return 0;
  return Math.max(1, Math.ceil(n * share));
}

// Ids of the top headlinerCount(nodes.length) nodes by weight. Ties at the cut keep input
// order (the API is weight desc), so the count is exact.
export function headlinerIds(nodes, share = HEADLINER_SHARE) {
  if (!Array.isArray(nodes) || nodes.length === 0) return new Set();
  const k = headlinerCount(nodes.length, share);
  const ranked = nodes
    .map((n, i) => ({ id: n.id, w: Number(n.weight) || 0, i }))
    .sort((a, b) => (b.w - a.w) || (a.i - b.i));
  return new Set(ranked.slice(0, k).map((r) => r.id));
}

function safeLog(w) {
  return Math.log(Math.max(1, Number(w) || 1));
}

// Log-interpolate weight between [minW, maxW] into an integer bucket.
// Equal bounds (single node or flat set) land in the middle bucket.
export function bucketForWeight(weight, minW, maxW, buckets = NODE_SCALE_BUCKETS) {
  const top = buckets - 1;
  if (!(maxW > minW)) return Math.floor(top / 2);
  const w = Math.max(minW, Math.min(maxW, Number(weight) || minW));
  const lo = safeLog(minW);
  const hi = safeLog(maxW);
  if (!(hi > lo)) return Math.floor(top / 2);
  const t = (safeLog(w) - lo) / (hi - lo);
  return Math.min(top, Math.max(0, Math.round(t * top)));
}

export function weightBounds(nodes) {
  let minW = Infinity;
  let maxW = -Infinity;
  for (const n of nodes) {
    const w = Number(n.weight) || 0;
    if (w < minW) minW = w;
    if (w > maxW) maxW = w;
  }
  if (!Number.isFinite(minW)) return { minW: 0, maxW: 0 };
  return { minW, maxW };
}

// Returns a new array with each node copied and given a `bucket` field. Headliners get
// HEADLINER_BUCKET; pass `headliners` (a Set of ids computed over the full set) to pin them
// when scaling a subset, otherwise they are derived from the nodes given.
export function scaleNodes(nodes, buckets = NODE_SCALE_BUCKETS, headliners = null) {
  if (!Array.isArray(nodes) || nodes.length === 0) return [];
  const { minW, maxW } = weightBounds(nodes);
  const top = headliners || headlinerIds(nodes);
  return nodes.map((n) => ({
    ...n,
    bucket: top.has(n.id) ? buckets : bucketForWeight(n.weight, minW, maxW, buckets),
  }));
}
