import { get, post, patch, del } from './client';

export function getAgents(params = {}) {
  return get('/agents', params);
}

export function getAgent(id) {
  return get(`/agents/${id}`);
}

export function createAgent(data) {
  return post('/agents', data);
}

export function updateAgent(id, data) {
  return patch(`/agents/${id}`, data);
}

export function deleteAgent(id) {
  return del(`/agents/${id}`);
}
