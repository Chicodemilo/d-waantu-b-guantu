// Path: src/api/activityLogs.js
// File: activityLogs.js
// Created: 2026-03-29
// Purpose: API functions for fetching and creating activity log entries
// Caller: hooks/useAppData.js, hooks/useActivityData.js
// Callees: ./client (get, post)
// Data In: Optional query params for listing; log data object for creation
// Data Out: Activity log objects or arrays from the /activity-logs endpoint
// Last Modified: 2026-03-29

import { get, post } from './client';

export function getActivityLogs(params = {}) {
  return get('/activity-logs', params);
}

export function getActivityLog(id) {
  return get(`/activity-logs/${id}`);
}

export function createActivityLog(data) {
  return post('/activity-logs', data);
}
