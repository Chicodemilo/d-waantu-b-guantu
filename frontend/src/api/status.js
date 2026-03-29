// Path: src/api/status.js
// File: status.js
// Created: 2026-03-29
// Purpose: API functions for system status, test coverage, and code standards endpoints
// Caller: pages/InstructionsPage.jsx, hooks/useAppData.js, hooks/usePolling.js, components/tests/TestCoverage.jsx
// Callees: ./client (get)
// Data In: No parameters required
// Data Out: Status object, test coverage data, code standards data
// Last Modified: 2026-03-29

import { get } from './client';

export function getStatus() {
  return get('/status');
}

export function getTestCoverage() {
  return get('/status/test-coverage');
}

export function getCodeStandards() {
  return get('/status/code-standards');
}
