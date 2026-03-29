import { get } from './client';

export function getTestRuns(params = {}) {
  return get('/test-results', params);
}

export function getTestRun(id) {
  return get(`/test-results/${id}`);
}

export function getProjectTestRuns(projectId) {
  return get(`/projects/${projectId}/tests`);
}

export function getTestPerformance() {
  return get('/test-results/performance');
}
