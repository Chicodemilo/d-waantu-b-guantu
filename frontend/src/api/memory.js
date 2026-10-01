// Path: src/api/memory.js
// File: memory.js
// Created: 2026-09-30 (DWB-613)
// Purpose: API functions for the human_memory read surfaces - the derived
//          score (GET /agents/:id/memory/scored) and the journal search
//          (GET /journal). View-only: both endpoints this module wraps are
//          reads. Journal writes stay agent-side (POST /api/journal), not a
//          UI concern per the ticket's scope.
// Caller: components/agents/AgentMemoryPanel.jsx, pages/JournalPage.jsx
// Callees: ./client (get)
// Data In: agentId; journal search filters (tags, term, date_from, date_to)
// Data Out: ScoredMemoryResponse shape; JournalSearchResponse shape
// Last Modified: 2026-09-30 (DWB-613)

import { get } from './client';

export function getScoredMemory(agentId) {
  return get(`/agents/${agentId}/memory/scored`);
}

// The journal never returns a full dump - the backend refuses a request with
// none of tags/date_from/date_to/term (422). This function does not soften
// that: it sends whatever filters it is given and lets the caller show the
// backend's own refusal message rather than inventing a friendlier one that
// could drift from the real rule.
//
// `tags` is repeated-query-param on the wire (`tags=a&tags=b`), which the
// shared `get()` helper's plain `URLSearchParams.set` cannot express (it
// would keep only the last tag). Built directly here instead, kept local to
// this one call rather than changing the shared client for one endpoint.
export function searchJournal({ agentId, tags, dateFrom, dateTo, term, limit } = {}) {
  const params = new URLSearchParams();
  if (agentId != null) params.append('agent_id', agentId);
  for (const t of tags || []) {
    const trimmed = (t || '').trim();
    if (trimmed) params.append('tags', trimmed);
  }
  if (dateFrom) params.append('date_from', dateFrom);
  if (dateTo) params.append('date_to', dateTo);
  if (term && term.trim()) params.append('term', term.trim());
  if (limit) params.append('limit', limit);

  const qs = params.toString();
  return get(qs ? `/journal?${qs}` : '/journal');
}
