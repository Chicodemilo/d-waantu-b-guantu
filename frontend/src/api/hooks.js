// Path: src/api/hooks.js
// File: hooks.js
// Created: 2026-04-09
// Purpose: API functions for fetching hook session data (active/completed sessions from passive tracking)
// Caller: hooks/useAppData.js, components/project/LiveSessions.jsx
// Callees: ./client (get)
// Data In: Optional filter params (project_id, status)
// Data Out: Hook session arrays or single session objects
// Last Modified: 2026-04-09

import { get } from './client';

export function getHookSessions(params = {}) {
  return get('/hooks/sessions', params);
}

export function getHookSession(sessionId) {
  return get(`/hooks/sessions/${sessionId}`);
}
