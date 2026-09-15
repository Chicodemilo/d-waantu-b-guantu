// Path: src/components/nodes/NodeCloud.jsx
// File: NodeCloud.jsx
// Created: 2026-09-15
// Purpose: Weighted tag cloud for the node index (DWB-534). Renders nodes in the order given (API is weight desc, so the order is stable) as text buttons sized by a log bucket (utils/nodeScale), each showing tag + pointer count. Caps the DOM at pageSize with a "show more" text link so a 3.6k-node project stays usable. Clicking a node calls onSelect(node); the selected node is marked with aria-pressed for the detail overlay consumer (DWB-535).
// Caller: pages/NodesPage.jsx
// Callees: react (useState, useEffect), utils/nodeScale (scaleNodes)
// Data In: nodes (NodeRead[]), onSelect (fn(node)), selectedId (number|null), pageSize (number)
// Data Out: default export NodeCloud component
// Last Modified: 2026-09-15

import { useState, useEffect, useMemo } from 'react';
import { scaleNodes } from '../../utils/nodeScale';

export const NODE_CLOUD_PAGE_SIZE = 500;

function NodeCloud({ nodes, onSelect, selectedId = null, pageSize = NODE_CLOUD_PAGE_SIZE }) {
  const [visibleCount, setVisibleCount] = useState(pageSize);

  // A new node set (initial load or a limiter result) restarts the cap.
  useEffect(() => {
    setVisibleCount(pageSize);
  }, [nodes, pageSize]);

  const scaled = useMemo(() => scaleNodes(nodes), [nodes]);
  const visible = scaled.slice(0, visibleCount);
  const hidden = scaled.length - visible.length;

  return (
    <div className="node-cloud" data-testid="node-cloud">
      <div className="node-cloud__cloud">
        {visible.map((node) => {
          const count = Array.isArray(node.pointers) ? node.pointers.length : 0;
          const selected = selectedId != null && node.id === selectedId;
          return (
            <button
              key={node.id}
              type="button"
              className={`node-cloud__node node-cloud__node--b${node.bucket}${selected ? ' node-cloud__node--selected' : ''}`}
              data-bucket={node.bucket}
              data-weight={node.weight}
              aria-pressed={selected}
              title={`${node.tag}: weight ${node.weight}, ${count} pointer${count === 1 ? '' : 's'}`}
              onClick={() => onSelect && onSelect(node)}
            >
              <span className="node-cloud__tag">{node.tag}</span>
              <span className="node-cloud__count">{count}</span>
            </button>
          );
        })}
      </div>
      <div className="node-cloud__foot">
        <span className="node-cloud__showing">
          showing {visible.length} of {scaled.length}
        </span>
        {hidden > 0 && (
          <button
            type="button"
            className="node-cloud__more"
            onClick={() => setVisibleCount((c) => c + pageSize)}
          >
            show more ({Math.min(hidden, pageSize)})
          </button>
        )}
        {hidden > pageSize && (
          <button
            type="button"
            className="node-cloud__more"
            onClick={() => setVisibleCount(scaled.length)}
          >
            show all
          </button>
        )}
      </div>
    </div>
  );
}

export default NodeCloud;
