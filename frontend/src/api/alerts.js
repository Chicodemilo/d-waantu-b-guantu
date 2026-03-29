// Path: src/api/alerts.js
// File: alerts.js
// Created: 2026-03-29
// Purpose: API functions for alerts including fetch, create, update, dismiss-all, and test run requests
// Caller: store/useStore.js, pages/ProjectTestsPage.jsx, pages/DashboardPage.jsx, pages/ProjectPage.jsx, hooks/useAlertsData.js, hooks/useAppData.js
// Callees: ./client (get, post, patch)
// Data In: Alert ID, alert data object, project ID for test runs, query params for listing
// Data Out: Alert objects/arrays from /alerts endpoint; test run trigger responses
// Last Modified: 2026-03-29

import { get, post, patch } from './client';

export function getAlerts(params = {}) {
  return get('/alerts', params);
}

export function getAlert(id) {
  return get(`/alerts/${id}`);
}

export function createAlert(data) {
  return post('/alerts', data);
}

export function updateAlert(id, data) {
  return patch(`/alerts/${id}`, data);
}

export function requestTestRun(projectId) {
  return post('/alerts/run-tests', { project_id: projectId });
}

export function dismissAllAlerts() {
  return post('/alerts/dismiss-all', {});
}
