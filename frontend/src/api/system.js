// Path: src/api/system.js
// File: system.js
// Created: 2026-03-29
// Purpose: API functions for system-level actions (run tests)
// Caller: pages/TestResultsPage.jsx, pages/ProjectTestsPage.jsx
// Callees: ./client (post)
// Data In: projectId (required — DWB-571, the endpoint has no default)
// Data Out: Test run result {passed, failed, total, status}
// Last Modified: 2026-09-16 (DWB-571: projectId is required and threaded through as a query param; the endpoint no longer defaults to project 1)

import { post } from './client';

export function runSystemTests(projectId) {
  const qs = new URLSearchParams({ project_id: projectId }).toString();
  return post(`/system/run-tests?${qs}`);
}
