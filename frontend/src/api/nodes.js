// Path: src/api/nodes.js
// File: nodes.js
// Created: 2026-09-15
// Purpose: API wrappers for the project node index (S81 Nodes, DWB-534/535/536/551). getProjectNodes returns the weight-ordered NodeRead list (id, project_id, tag, weight, pointers[id, kind, ref, sha, line_start, line_end]); matchProjectNodes normalizes free text to tags and returns {query, query_tags, nodes[...NodeRead + neighbors[id, tag, weight, shared_refs]]}. Shapes bound field-for-field against the live backend/app/routers/nodes.py.
// Caller: hooks/useProjectNodes.js (list), hooks/useNodeConnections.js (connections fan-out, DWB-543), hooks/useNodeDetail.js (detail + neighbor hop match), hooks/useNodeify.js (rescan, DWB-551)
// Callees: ./client (get, post)
// Data In: projectId (number|string), optional { kind } filter, free text query, optional { signal }
// Data Out: Promise<NodeRead[]>; Promise<NodeMatchResponse>; Promise<NodeifyResponse>
// Last Modified: 2026-09-15 (DWB-551: nodeify)

import { get, post } from './client';

// GET /projects/{id}/nodes -> list[NodeRead], weight desc. kind: code|memory|doc|ticket|session.
export function getProjectNodes(projectId, params = {}, options = {}) {
  return get(`/projects/${projectId}/nodes`, params, options);
}

// GET /projects/{id}/nodes/match?text=... -> { query, query_tags, nodes }.
export function matchProjectNodes(projectId, text, options = {}) {
  return get(`/projects/${projectId}/nodes/match`, { text }, options);
}

// POST /projects/{id}/nodeify -> NodeifyResponse { project_id, nodeified_at,
// source_counts, grounded, pruned, suppressed, pointers_written }. The operator
// rebuild; idempotent, but a concurrent second pass 500s, so callers guard.
export function nodeifyProject(projectId, options = {}) {
  return post(`/projects/${projectId}/nodeify`, undefined, options);
}
