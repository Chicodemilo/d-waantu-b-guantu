// Path: src/services/tracking.js
// File: tracking.js
// Created: 2026-03-29
// Purpose: Tracking API client for fetching pre-computed token/time summaries per project
// Caller: Components that display token/time rollups (TokenOverview, ProjectCard, ProjectHeader, EpicList, SprintProgress, CrossProjectSummary, TimeTokens)
// Callees: ../api/client (get)
// Data In: Project ID, optional { signal } AbortController signal
// Data Out: Tracking summary {per_ticket, per_agent, per_sprint, project_total}
// Last Modified: 2026-06-10

import { get } from '../api/client';

export function getTrackingSummary(projectId, options = {}) {
  return get('/tracking/summary', { project_id: projectId }, { signal: options.signal });
}
