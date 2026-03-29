// Path: src/api/failureRecords.js
// File: failureRecords.js
// Created: 2026-03-29
// Purpose: API functions for failure records including summary, listing, creation, and updates
// Caller: components/tests/FailureAnalysis.jsx
// Callees: ./client (get, post, patch)
// Data In: Project ID for scoped queries; failure record ID and data for updates; record data for creation
// Data Out: Failure summary object, failure record arrays, created/updated record objects
// Last Modified: 2026-03-29

import { get, post, patch } from './client';

export function getFailureSummary(projectId) {
  return get('/failure-records/summary', { project_id: projectId });
}

export function getFailureRecords(projectId) {
  return get('/failure-records', { project_id: projectId });
}

export function createFailureRecord(data) {
  return post('/failure-records', data);
}

export function updateFailureRecord(id, data) {
  return patch(`/failure-records/${id}`, data);
}
