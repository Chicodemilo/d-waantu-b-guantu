// Path: src/api/docs.js
// File: docs.js
// Created: 2026-03-29
// Purpose: API functions to fetch project and system documentation status and content
// Caller: pages/DocsPage.jsx, pages/SystemDocsPage.jsx
// Callees: ./client (get)
// Data In: Project ID (for project docs), nothing (for system docs)
// Data Out: Array of {name, path, exists, content}
// Last Modified: 2026-03-29

import { get } from './client';

export function getProjectDocs(projectId) {
  return get(`/projects/${projectId}/docs`);
}

export function getSystemDocs() {
  return get('/system/docs');
}
