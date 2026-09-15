// Path: src/components/nodes/NodeDetail.jsx
// File: NodeDetail.jsx
// Created: 2026-09-15
// Purpose: Node detail content for the overlay (DWB-535): tag, weight, pointer count, pointers grouped by kind with ref + line range (text only, no navigation), and derived neighbors with their shared_refs count from the match endpoint. Clicking a neighbor hops: the content swaps in place via hooks/useNodeDetail and a breadcrumb trail with a back link shows the path. Neighbors sort by shared refs desc then weight desc and are capped with a show more link.
// Caller: pages/NodesPage.jsx (as the child of components/common/Overlay)
// Callees: react (useState, useMemo, useEffect), hooks/useNodeDetail
// Data In: projectId, node (seed from the cloud: id, tag, weight, pointers)
// Data Out: default export NodeDetail component
// Last Modified: 2026-09-15

import { useState, useMemo, useEffect } from 'react';
import useNodeDetail from '../../hooks/useNodeDetail';

export const NEIGHBOR_PAGE_SIZE = 40;
const KIND_ORDER = ['code', 'doc', 'memory', 'ticket', 'session'];

function lineRange(p) {
  if (p.line_start == null) return '';
  if (p.line_end == null || p.line_end === p.line_start) return `:${p.line_start}`;
  return `:${p.line_start}-${p.line_end}`;
}

function groupPointers(pointers) {
  const groups = new Map();
  for (const p of pointers || []) {
    const kind = p.kind || 'other';
    if (!groups.has(kind)) groups.set(kind, []);
    groups.get(kind).push(p);
  }
  const known = KIND_ORDER.filter((k) => groups.has(k));
  const rest = [...groups.keys()].filter((k) => !KIND_ORDER.includes(k)).sort();
  return [...known, ...rest].map((kind) => ({ kind, items: groups.get(kind) }));
}

function NodeDetail({ projectId, node: seed }) {
  const { node, pointers, neighbors, loading, error, trail, hop, back } = useNodeDetail(projectId, seed);
  const [neighborCount, setNeighborCount] = useState(NEIGHBOR_PAGE_SIZE);

  useEffect(() => {
    setNeighborCount(NEIGHBOR_PAGE_SIZE);
  }, [node?.id]);

  const groups = useMemo(() => groupPointers(pointers), [pointers]);
  const sortedNeighbors = useMemo(() => {
    const list = Array.isArray(neighbors) ? [...neighbors] : [];
    list.sort((a, b) => {
      const d = (b.shared_refs?.length || 0) - (a.shared_refs?.length || 0);
      return d !== 0 ? d : (b.weight || 0) - (a.weight || 0);
    });
    return list;
  }, [neighbors]);

  if (!node) return null;

  const pointerTotal = Array.isArray(pointers) ? pointers.length : 0;
  const visibleNeighbors = sortedNeighbors.slice(0, neighborCount);
  const hiddenNeighbors = sortedNeighbors.length - visibleNeighbors.length;

  return (
    <div className="node-detail" data-testid="node-detail">
      {trail.length > 1 && (
        <div className="node-detail__trail">
          <span className="node-detail__trail-label">hop</span>
          {trail.map((t, i) => (
            <span key={`${t.id}-${i}`} className="node-detail__trail-item">
              {i > 0 && <span className="node-detail__trail-sep">&gt;</span>}
              {t.tag}
            </span>
          ))}
          <button type="button" className="node-detail__link" onClick={back}>back</button>
        </div>
      )}

      <div className="node-detail__head">
        <span className="node-detail__tag">{node.tag}</span>
        <span className="node-detail__meta">weight {node.weight}</span>
        <span className="node-detail__meta">
          {pointers == null ? 'pointers ...' : `${pointerTotal} pointer${pointerTotal === 1 ? '' : 's'}`}
        </span>
        {loading && <span className="node-detail__meta node-detail__loading">loading neighbors...</span>}
      </div>

      {error && (
        <div className="node-detail__error">match lookup failed: {error.message || 'unknown error'}</div>
      )}

      <div className="node-detail__section-title">pointers</div>
      {pointers != null && pointerTotal === 0 && (
        <div className="node-detail__empty">no pointers</div>
      )}
      {groups.map(({ kind, items }) => (
        <div key={kind} className="node-detail__group">
          <div className="node-detail__kind">
            {kind} <span className="node-detail__kind-count">{items.length}</span>
          </div>
          <ul className="node-detail__pointers">
            {items.map((p) => (
              <li key={p.id ?? `${p.ref}${lineRange(p)}`} className="node-detail__pointer">
                <span className="node-detail__ref">{p.ref}</span>
                <span className="node-detail__lines">{lineRange(p)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="node-detail__section-title">
        neighbors
        {neighbors != null && <span className="node-detail__kind-count">{sortedNeighbors.length}</span>}
      </div>
      {neighbors != null && sortedNeighbors.length === 0 && !loading && (
        <div className="node-detail__empty">no neighbors share a ref with this node</div>
      )}
      {visibleNeighbors.length > 0 && (
        <ul className="node-detail__neighbors">
          {visibleNeighbors.map((nb) => {
            const shared = nb.shared_refs?.length || 0;
            return (
              <li key={nb.id} className="node-detail__neighbor">
                <button
                  type="button"
                  className="node-detail__neighbor-btn"
                  title={(nb.shared_refs || []).join('\n')}
                  onClick={() => hop(nb)}
                >
                  <span className="node-detail__neighbor-tag">{nb.tag}</span>
                  <span className="node-detail__neighbor-meta">w{nb.weight}</span>
                  <span className="node-detail__neighbor-meta">{shared} shared</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {hiddenNeighbors > 0 && (
        <div className="node-detail__foot">
          <span>showing {visibleNeighbors.length} of {sortedNeighbors.length}</span>
          <button
            type="button"
            className="node-detail__link"
            onClick={() => setNeighborCount((c) => c + NEIGHBOR_PAGE_SIZE)}
          >
            show more ({Math.min(hiddenNeighbors, NEIGHBOR_PAGE_SIZE)})
          </button>
        </div>
      )}
    </div>
  );
}

export default NodeDetail;
