// Path: src/api/sessions.js
// File: sessions.js
// Created: 2026-06-10
// Purpose: API wrappers for DWB session list (per project), session detail (by_role, by_ticket, overhead, live), the DWBG-012 cross-project session recall search, and the DWBG-016 cross-project recent-sessions feed
// Caller: components/project/SessionPanel.jsx, pages/SessionRecallPage.jsx
// Callees: ./client (get)
// Data In: projectId for list, sessionId for detail, search terms + optional facets for recall, limit/offset for recent
// Data Out: Session list arrays, single session detail object, ranked slim search-result rows, or newest-first slim recent rows
// Last Modified: 2026-06-25 (DWBG-016: add getRecentSessions cross-project recent feed)

import { get } from './client';

export function getProjectSessions(projectId) {
  return get(`/projects/${projectId}/sessions`);
}

export function getSession(sessionId) {
  return get(`/sessions/${sessionId}`);
}

// DWBG-012: cross-project Session Recall search (DWBG-011 contract).
// GET /api/sessions/search?q=<terms>&project_id=&agent_id=&epic_id=&from=&to=
// `q` is required; facets are optional (omitted -> cross-project). Returns a
// ranked list of slim rows: { id, project_id, headline, opened_at, closed_at,
// total_tokens, snippet, keywords: [{ keyword, weight }] }.
// `get` drops null/undefined params, so unset facets simply do not appear in the
// query string.
export function searchSessions({ q, projectId, agentId, epicId, from, to } = {}) {
  return get('/sessions/search', {
    q,
    project_id: projectId,
    agent_id: agentId,
    epic_id: epicId,
    from,
    to,
  });
}

// DWBG-016: cross-project recent-sessions feed (newest-first). Powers the default
// view of the Recall page so the operator no longer has to search to find a session.
// GET /api/sessions/recent?limit=&offset=
// Returns slim rows: { id, project_id, headline, opened_at, closed_at,
// total_tokens, keywords: [{ keyword, weight }] }. (No `snippet` — there is no
// query to highlight against.) `get` drops null/undefined params.
export function getRecentSessions({ limit, offset } = {}) {
  return get('/sessions/recent', { limit, offset });
}
