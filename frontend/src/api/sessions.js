// Path: src/api/sessions.js
// File: sessions.js
// Created: 2026-06-10
// Purpose: API wrappers for DWB session list (per project) and session detail (by_role, by_ticket, overhead, live)
// Caller: components/project/SessionPanel.jsx
// Callees: ./client (get)
// Data In: projectId for list, sessionId for detail
// Data Out: Session list arrays or single session detail object
// Last Modified: 2026-06-10

import { get } from './client';

export function getProjectSessions(projectId) {
  return get(`/projects/${projectId}/sessions`);
}

export function getSession(sessionId) {
  return get(`/sessions/${sessionId}`);
}
