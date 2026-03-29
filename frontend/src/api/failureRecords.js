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
