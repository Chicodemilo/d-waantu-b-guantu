// Path: src/pages/NodesPage.jsx
// File: NodesPage.jsx
// Created: 2026-09-15
// Purpose: Project Nodes page (DWB-534/535/536): renders the node index as a weighted tag cloud with loading and empty states (the empty state points at POST /api/projects/{id}/nodeify). Owns the selected-node state; a selection opens the generic Overlay with NodeDetail inside (DWB-535). The match search box is a LIMITER (Miles ruling, DWB-536): a debounced GET /nodes/match narrows the cloud to the matching node ids, non-matches disappear, matches keep their full-set weight scale via the cloud's bounds prop, and an empty query restores the full cloud. Esc or the clear link empties the query.
// Caller: App.jsx (route: /projects/:id/nodes)
// Callees: react (useState, useMemo), react-router-dom (useParams), store/useStore (getProject), hooks/useProjectNodes, hooks/useNodeMatch, utils/nodeScale (weightBounds), components/nodes/NodeCloud, components/nodes/NodeDetail, components/common/Overlay, components/common/FuzzySearch
// Data In: Route param (id), project from Zustand store, nodes from API
// Data Out: Default export NodesPage component
// Last Modified: 2026-09-15 (DWB-536)

import { useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import useProjectNodes from '../hooks/useProjectNodes';
import useNodeMatch from '../hooks/useNodeMatch';
import { weightBounds } from '../utils/nodeScale';
import FuzzySearch from '../components/common/FuzzySearch';
import NodeCloud from '../components/nodes/NodeCloud';
import NodeDetail from '../components/nodes/NodeDetail';
import Overlay from '../components/common/Overlay';

function NodesPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const { nodes, pointerTotal, loading, error, reload } = useProjectNodes(id);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const { matchIds, queryTags, loading: matching, error: matchError, settledQuery } = useNodeMatch(id, query);

  // Scale is pinned to the FULL set so a limited cloud keeps each node's size.
  const bounds = useMemo(() => weightBounds(nodes), [nodes]);
  const limiting = matchIds != null;
  const visibleNodes = useMemo(
    () => (limiting ? nodes.filter((n) => matchIds.has(n.id)) : nodes),
    [nodes, matchIds, limiting]
  );
  const clearQuery = () => setQuery('');

  const prefix = project?.prefix ? project.prefix.toLowerCase() : `project ${id}`;

  let body;
  if (loading) {
    body = <div className="empty-state nodes-page__loading">loading nodes...</div>;
  } else if (error) {
    body = (
      <div className="empty-state nodes-page__error">
        failed to load nodes: {error.message || 'unknown error'}{' '}
        <button type="button" className="nodes-page__link" onClick={reload}>retry</button>
      </div>
    );
  } else if (nodes.length === 0) {
    body = (
      <div className="empty-state nodes-page__empty">
        <div>no nodes indexed for this project yet.</div>
        <div className="nodes-page__hint">
          build the index with <code className="nodes-page__code">POST /api/projects/{id}/nodeify</code>, then{' '}
          <button type="button" className="nodes-page__link" onClick={reload}>reload</button>.
        </div>
      </div>
    );
  } else {
    body = (
      <>
        <div className="nodes-page__search">
          <FuzzySearch
            value={query}
            onChange={setQuery}
            onEscape={clearQuery}
            label="match"
            placeholder="limit the cloud to nodes matching this text..."
            resultCount={limiting ? visibleNodes.length : null}
            totalCount={nodes.length}
          />
          {query.trim() !== '' && (
            <div className="nodes-page__tags" data-testid="query-tags">
              <span className="nodes-page__tags-label">tags</span>
              {matching && !limiting && <span className="nodes-page__tags-pending">matching...</span>}
              {limiting && queryTags.length === 0 && <span className="nodes-page__tags-none">none</span>}
              {queryTags.map((t) => (
                <span key={t} className="nodes-page__tag">{t}</span>
              ))}
              {matching && limiting && <span className="nodes-page__tags-pending">...</span>}
            </div>
          )}
          {matchError && (
            <div className="nodes-page__match-error">match failed: {matchError.message || 'unknown error'}</div>
          )}
        </div>
        {limiting && visibleNodes.length === 0 ? (
          <div className="empty-state nodes-page__no-match">
            no nodes match &quot;{settledQuery}&quot;.{' '}
            <button type="button" className="nodes-page__link" onClick={clearQuery}>clear</button>
          </div>
        ) : (
          <NodeCloud
            nodes={visibleNodes}
            bounds={bounds}
            onSelect={setSelected}
            selectedId={selected ? selected.id : null}
          />
        )}
      </>
    );
  }

  return (
    <div className="nodes-page">
      <div className="nodes-page__head">
        <span className="nodes-page__title">{prefix} / nodes</span>
        {!loading && !error && nodes.length > 0 && (
          <span className="nodes-page__count">
            {nodes.length} node{nodes.length === 1 ? '' : 's'}, {pointerTotal} pointer{pointerTotal === 1 ? '' : 's'}
          </span>
        )}
      </div>
      {body}
      <Overlay
        open={selected != null}
        onClose={() => setSelected(null)}
        label={selected ? `node ${selected.tag}` : 'node detail'}
      >
        {selected && <NodeDetail projectId={id} node={selected} />}
      </Overlay>
    </div>
  );
}

export default NodesPage;
