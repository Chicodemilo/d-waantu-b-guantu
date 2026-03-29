// Path: src/api/testResults.js
// File: testResults.js
// Created: 2026-03-29
// Purpose: API functions for fetching test runs, project-specific test runs, and test performance data
// Caller: pages/ProjectTestsPage.jsx, hooks/useAppData.js, components/project/ProjectHeader.jsx, components/tests/TestPerformance.jsx
// Callees: ./client (get)
// Data In: Test run ID for single fetch; project ID for project-scoped runs; query params for listing
// Data Out: Test run objects/arrays, performance data from /test-results endpoint
// Last Modified: 2026-03-29

import { get } from './client';

export function getTestRuns(params = {}) {
  return get('/test-results', params);
}

export function getTestRun(id) {
  return get(`/test-results/${id}`);
}

export function getProjectTestRuns(projectId) {
  return get(`/projects/${projectId}/tests`);
}

export function getTestPerformance() {
  return get('/test-results/performance');
}
