// Path: src/utils/nodeScale.js
// File: nodeScale.js
// Created: 2026-09-15
// Purpose: Pure weight-to-size bucketing for the node cloud (DWB-534). Maps a node weight onto a small fixed number of log-spaced buckets so the top nodes share one cap size instead of dwarfing the page; the CSS assigns a font-size per bucket. Bucket boundaries derive from the min/max of the set passed in, so the scale re-fits when the cloud is limited by a search.
// Caller: hooks/useProjectNodes.js, components/nodes/NodeCloud.jsx, nodeScale.test.js
// Callees: None (leaf utility module)
// Data In: node weight (number), weight bounds, node arrays [{weight, ...}]
// Data Out: bucket index 0..buckets-1; nodes decorated with a bucket field
// Last Modified: 2026-09-15

export const NODE_SCALE_BUCKETS = 8;

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

// Returns a new array with each node copied and given a `bucket` field.
export function scaleNodes(nodes, buckets = NODE_SCALE_BUCKETS) {
  if (!Array.isArray(nodes) || nodes.length === 0) return [];
  const { minW, maxW } = weightBounds(nodes);
  return nodes.map((n) => ({ ...n, bucket: bucketForWeight(n.weight, minW, maxW, buckets) }));
}
