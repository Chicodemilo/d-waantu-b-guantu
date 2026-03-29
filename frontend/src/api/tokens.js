// Path: src/api/tokens.js
// File: tokens.js
// Created: 2026-03-29
// Purpose: API function for fetching token audit data
// Caller: components/dashboard/TokenAudit.jsx
// Callees: ./client (get)
// Data In: No parameters required
// Data Out: Token audit data from the /tokens/audit endpoint
// Last Modified: 2026-03-29

import { get } from './client';

export function getTokenAudit() {
  return get('/tokens/audit');
}
