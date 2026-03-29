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
