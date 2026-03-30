// Path: src/api/system.js
// File: system.js
// Created: 2026-03-29
// Purpose: API functions for system-level actions (run tests)
// Caller: pages/TestResultsPage.jsx
// Callees: ./client (post)
// Data In: None
// Data Out: Test run result {passed, failed, total, status}
// Last Modified: 2026-03-29

import { post } from './client';

export function runSystemTests() {
  return post('/system/run-tests');
}
