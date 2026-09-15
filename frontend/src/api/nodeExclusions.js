// Path: src/api/nodeExclusions.js
// File: nodeExclusions.js
// Created: 2026-09-15
// Purpose: API wrappers for the per-project node scan exclusions and the repo directory browse used to pick them (DWB-552 UI over Stan's DWB-549 and DWB-553 endpoints). Rows are {id, project_id, pattern, created_at}; patterns are repo-relative paths or globs and there is deliberately no is_default flag, because seeded defaults are ordinary deletable rows. Bound field for field against the live API on 2026-09-15.
// Caller: hooks/useNodeExclusions.js, hooks/useRepoDirectories.js
// Callees: ./client (get, post, del)
// Data In: projectId, pattern string, exclusion id, repo-relative parent path, optional { signal }
// Data Out: Promise<ExclusionRow[]>; Promise<ExclusionRow>; Promise<null> (DELETE is 204); Promise<{parent, directories[{name, path}]}>
// Last Modified: 2026-09-15 (DWB-553 browse)

import { get, post, del } from './client';

// GET -> array of {id, project_id, pattern, created_at}, seeded rows included.
export function getNodeExclusions(projectId, options = {}) {
  return get(`/projects/${projectId}/node-exclusions`, {}, options);
}

// POST {pattern} -> 201 with the created row. Rejects with ApiError carrying the
// server's detail text: 400 for empty, absolute or traversing patterns, 409 for
// a pattern already excluded on this project.
export function createNodeExclusion(projectId, pattern, options = {}) {
  return post(`/projects/${projectId}/node-exclusions`, { pattern }, options);
}

// DELETE -> 204 (null). 404 when the row is already gone.
export function deleteNodeExclusion(projectId, exclusionId, options = {}) {
  return del(`/projects/${projectId}/node-exclusions/${exclusionId}`, options);
}

// GET /repo-directories?parent=<repo-relative path> -> {parent, directories[{name, path}]}
// (DWB-553). One level per call, directories only, sorted by name. `parent` echoes
// the normalized request, so a breadcrumb is a split on "/". 400 for absolute or
// traversing parents, 404 for a directory that does not exist.
export function getRepoDirectories(projectId, parent = '', options = {}) {
  return get(`/projects/${projectId}/repo-directories`, { parent }, options);
}
