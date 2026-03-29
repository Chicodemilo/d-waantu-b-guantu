// Path: src/api/docs.js
// File: docs.js
// Created: 2026-03-29
// Purpose: API function to fetch project documentation status and content
// Caller: pages/DocsPage.jsx
// Callees: ./client (get)
// Data In: Project ID
// Data Out: Array of {name, path, exists, content}
// Last Modified: 2026-03-29

import { get } from './client';

export function getProjectDocs(projectId) {
  return get(`/projects/${projectId}/docs`);
}
