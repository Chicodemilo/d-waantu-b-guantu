// Path: src/pages/NodesPage.jsx
// File: NodesPage.jsx
// Created: 2026-09-15
// Purpose: Project Nodes page (DWB-534/535/536/541/542/543): renders the node index as a weighted tag cloud with loading and empty states (the empty state points at POST /api/projects/{id}/nodeify). Owns the selected-node state; a selection opens the generic Overlay with NodeDetail inside (DWB-535). The search box is a LIMITER (Miles ruling): a client-side case-insensitive substring filter on node.tag over the loaded set (DWB-543, replacing the exact-tag server match of DWB-536); non-matches disappear, matches keep their full-set weight scale via the cloud's bounds prop and their headliner tier via headlinerIds (DWB-541), an empty query restores the full cloud, Esc or the clear link empties the query. An optional "+ connections" toggle (OFF by default) adds first-degree neighbors of the matches in a dimmed style via hooks/useNodeConnections when 25 or fewer nodes match; above that it is disabled. A pointer-kind toggle row (DWB-542) filters client-side over loaded pointers and composes with the search (both must pass); all kinds off shows "no kinds selected" with a select-all link.
// Caller: App.jsx (route: /projects/:id/nodes)
// Callees: react (useState, useMemo), react-router-dom (useParams), store/useStore (getProject), hooks/useProjectNodes, hooks/useNodeConnections, utils/nodeScale (weightBounds, headlinerIds), utils/nodeKinds (pointerKinds, nodeHasSelectedKind), components/nodes/KindFilter, components/nodes/NodeCloud, components/nodes/NodeDetail, components/common/Overlay, components/common/FuzzySearch
// Data In: Route param (id), project from Zustand store, nodes from API
// Data Out: Default export NodesPage component
// Last Modified: 2026-09-15 (DWB-543)

import { useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import useProjectNodes from '../hooks/useProjectNodes';
import useNodeConnections, { MAX_CONNECTION_MATCHES } from '../hooks/useNodeConnections';
import { weightBounds, headlinerIds } from '../utils/nodeScale';
import { pointerKinds, nodeHasSelectedKind } from '../utils/nodeKinds';
import KindFilter from '../components/nodes/KindFilter';
import FuzzySearch from '../components/common/FuzzySearch';
import NodeCloud from '../components/nodes/NodeCloud';
import NodeDetail from '../components/nodes/NodeDetail';
import Overlay from '../components/common/Overlay';

const CONNECTIONS_TITLE_NARROW = 'narrow the search to show connections';
const CONNECTIONS_TITLE_EMPTY = 'search for a node to show its connections';

function NodesPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const { nodes, pointerTotal, loading, error, reload } = useProjectNodes(id);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [connectionsOn, setConnectionsOn] = useState(false);

  // Scale and headliner tier are pinned to the FULL set so a limited cloud keeps each node's size.
  const bounds = useMemo(() => weightBounds(nodes), [nodes]);
  const headliners = useMemo(() => headlinerIds(nodes), [nodes]);

  // Substring limiter (DWB-543): case-insensitive on node.tag, local, no debounce.
  const needle = query.trim().toLowerCase();
  const limiting = needle !== '';
  const matches = useMemo(
    () => (limiting ? nodes.filter((n) => (n.tag || '').toLowerCase().includes(needle)) : nodes),
    [nodes, needle, limiting]
  );
  const matchIds = useMemo(() => new Set(matches.map((n) => n.id)), [matches]);

  // Optional first-degree connections around a small match set.
  const searchMatches = useMemo(() => (limiting ? matches : []), [limiting, matches]);
  const { connectedIds, loading: connecting, error: connectionsError, eligible } = useNodeConnections(id, searchMatches, connectionsOn);
  const showingConnections = connectionsOn && limiting && eligible;

  // Pointer-kind filter (DWB-542): null = every kind selected (so kinds arriving later stay on).
  const [selectedKinds, setSelectedKinds] = useState(null);
  const kinds = useMemo(() => pointerKinds(nodes), [nodes]);
  const noKinds = selectedKinds != null && selectedKinds.size === 0;
  const toggleKind = (kind) => {
    setSelectedKinds((prev) => {
      const next = new Set(prev == null ? kinds.map((k) => k.kind) : prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };
  const selectAllKinds = () => setSelectedKinds(null);

  // Both filters must pass: kind, then search (a connected neighbor counts as passing the search).
  const visibleNodes = useMemo(
    () => nodes.filter((n) =>
      nodeHasSelectedKind(n, selectedKinds)
      && (!limiting || matchIds.has(n.id) || (showingConnections && connectedIds.has(n.id)))
    ),
    [nodes, selectedKinds, limiting, matchIds, showingConnections, connectedIds]
  );
  const visibleMatchCount = useMemo(
    () => (limiting ? visibleNodes.filter((n) => matchIds.has(n.id)).length : visibleNodes.length),
    [limiting, visibleNodes, matchIds]
  );
  const visibleConnectionCount = showingConnections ? visibleNodes.length - visibleMatchCount : 0;
  const clearQuery = () => setQuery('');

  const connectionsDisabled = !limiting || !eligible;
  const connectionsTitle = !limiting || matches.length === 0
    ? CONNECTIONS_TITLE_EMPTY
    : (eligible ? `show first-degree connections of the ${matches.length} match${matches.length === 1 ? '' : 'es'}` : CONNECTIONS_TITLE_NARROW);

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
            placeholder="limit the cloud to node names containing this text..."
            resultCount={limiting ? visibleMatchCount : null}
            totalCount={nodes.length}
          />
          <div className="nodes-page__connections">
            <button
              type="button"
              className={`nodes-page__connections-toggle${showingConnections ? ' nodes-page__connections-toggle--on' : ''}`}
              aria-pressed={connectionsOn}
              disabled={connectionsDisabled}
              title={connectionsTitle}
              onClick={() => setConnectionsOn((v) => !v)}
            >
              + connections
            </button>
            {showingConnections && connecting && <span className="nodes-page__connections-note">connecting...</span>}
            {showingConnections && !connecting && (
              <span className="nodes-page__connections-note">
                {visibleConnectionCount} connection{visibleConnectionCount === 1 ? '' : 's'} shown
              </span>
            )}
            {limiting && !eligible && matches.length > MAX_CONNECTION_MATCHES && (
              <span className="nodes-page__connections-note">{CONNECTIONS_TITLE_NARROW}</span>
            )}
            {connectionsError && (
              <span className="nodes-page__match-error">connections failed: {connectionsError.message || 'unknown error'}</span>
            )}
          </div>
        </div>
        <KindFilter kinds={kinds} selected={selectedKinds} onToggle={toggleKind} onSelectAll={selectAllKinds} />
        {noKinds ? (
          <div className="empty-state nodes-page__no-kinds">
            no kinds selected.{' '}
            <button type="button" className="nodes-page__link" onClick={selectAllKinds}>select all</button>
          </div>
        ) : limiting && visibleNodes.length === 0 ? (
          <div className="empty-state nodes-page__no-match">
            no nodes match &quot;{query.trim()}&quot;.{' '}
            <button type="button" className="nodes-page__link" onClick={clearQuery}>clear</button>
          </div>
        ) : (
          <NodeCloud
            nodes={visibleNodes}
            bounds={bounds}
            headlinerIds={headliners}
            connectedIds={showingConnections ? connectedIds : null}
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
