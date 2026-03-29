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
