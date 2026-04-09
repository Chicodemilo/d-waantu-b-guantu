// Path: src/api/errors.js
// File: errors.js
// Created: 2026-04-09
// Purpose: API functions for error log endpoints
// Caller: pages/ErrorLogPage.jsx
// Callees: ./client (get)
// Data In: Optional filter params (project_id, source, limit)
// Data Out: Error log arrays from /errors endpoint
// Last Modified: 2026-04-09

import { get } from './client';

export function getErrorLogs(params = {}) {
  return get('/errors', params);
}
