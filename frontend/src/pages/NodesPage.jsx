// Path: src/pages/NodesPage.jsx
// File: NodesPage.jsx
// Created: 2026-09-15
// Purpose: Project Nodes page (DWB-534): renders the node index as a weighted tag cloud with loading and empty states (the empty state points at POST /api/projects/{id}/nodeify). Owns the selected-node state that the detail overlay (DWB-535) consumes.
// Caller: App.jsx (route: /projects/:id/nodes)
// Callees: react (useState), react-router-dom (useParams), store/useStore (getProject), hooks/useProjectNodes, components/nodes/NodeCloud
// Data In: Route param (id), project from Zustand store, nodes from API
// Data Out: Default export NodesPage component
// Last Modified: 2026-09-15

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import useProjectNodes from '../hooks/useProjectNodes';
import NodeCloud from '../components/nodes/NodeCloud';

function NodesPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const { nodes, pointerTotal, loading, error, reload } = useProjectNodes(id);
  const [selected, setSelected] = useState(null);

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
      <NodeCloud
        nodes={nodes}
        onSelect={setSelected}
        selectedId={selected ? selected.id : null}
      />
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
    </div>
  );
}

export default NodesPage;
