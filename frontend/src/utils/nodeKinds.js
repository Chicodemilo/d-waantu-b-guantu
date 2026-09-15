// Path: src/utils/nodeKinds.js
// File: nodeKinds.js
// Created: 2026-09-15
// Purpose: Pure pointer-kind helpers for the node cloud kind filter (DWB-542). Lists the kinds present in a loaded node set in a fixed display order with a human label (doc -> "docs") and per-kind node counts, and decides whether a node passes a selected-kind set (visible when at least one pointer has a selected kind). Client-side over already loaded pointers; never calls the server ?kind filter.
// Caller: pages/NodesPage.jsx, components/nodes/KindFilter.jsx, nodeKinds.test.js
// Callees: None (leaf utility module)
// Data In: NodeRead[] with pointers[{kind}], Set<string> of selected kinds
// Data Out: [{kind, label, count}] ordered; boolean pass check
// Last Modified: 2026-09-15

export const KIND_ORDER = ['code', 'doc', 'memory', 'ticket', 'session'];
const KIND_LABELS = { code: 'code', doc: 'docs', memory: 'memory' };

export function kindLabel(kind) {
  return KIND_LABELS[kind] || kind;
}

// Kinds present in the set, ordered code, doc, memory, ticket, session, then any others alphabetically.
export function pointerKinds(nodes) {
  const counts = new Map();
  for (const n of nodes || []) {
    const seen = new Set();
    for (const p of n.pointers || []) {
      const k = p.kind || 'other';
      if (seen.has(k)) continue;
      seen.add(k);
      counts.set(k, (counts.get(k) || 0) + 1);
    }
  }
  const known = KIND_ORDER.filter((k) => counts.has(k));
  const rest = [...counts.keys()].filter((k) => !KIND_ORDER.includes(k)).sort();
  return [...known, ...rest].map((kind) => ({ kind, label: kindLabel(kind), count: counts.get(kind) }));
}

// A node stays visible when at least one of its pointers has a selected kind.
// selected === null means "all kinds", the initial state.
export function nodeHasSelectedKind(node, selected) {
  if (selected == null) return true;
  if (selected.size === 0) return false;
  return (node.pointers || []).some((p) => selected.has(p.kind || 'other'));
}
