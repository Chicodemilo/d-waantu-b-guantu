// Path: src/api/standardsAudits.js
// File: standardsAudits.js
// Created: 2026-08-12
// Purpose: API functions for fetching stored standards-audit scorecards: the slim per-project list and the full single-audit detail. Access goes through the shared client (never raw fetch) per the services doctrine.
// Caller: components/project/StandardsAudits.jsx, __tests__/StandardsAudits.test.jsx
// Callees: ./client (get)
// Data In: project ID for the list; audit ID for a single record; optional { signal } AbortController option
// Data Out: Audit objects/arrays from /standards-audits (verdict, pr_ref, violations[], scorecard[], summary)
// Last Modified: 2026-08-12 (DWB-018)

import { get } from './client';

export function getStandardsAudits(projectId, options = {}) {
  return get('/standards-audits', { project_id: projectId }, options);
}

export function getStandardsAudit(id, options = {}) {
  return get(`/standards-audits/${id}`, {}, options);
}
