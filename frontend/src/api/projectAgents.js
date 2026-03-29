import { get } from './client';

export function getProjectAgents(params = {}) {
  return get('/project-agents', params);
}
