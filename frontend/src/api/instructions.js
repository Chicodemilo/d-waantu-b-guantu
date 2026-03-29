import { get, post, patch, del } from './client';

export function getInstructions(params = {}) {
  return get('/instructions', params);
}

export function getInstruction(id) {
  return get(`/instructions/${id}`);
}

export function createInstruction(data) {
  return post('/instructions', data);
}

export function updateInstruction(id, data) {
  return patch(`/instructions/${id}`, data);
}

export function deleteInstruction(id) {
  return del(`/instructions/${id}`);
}

export function syncCheck() {
  return get('/instructions/sync-check');
}

export function syncInstructions() {
  return post('/instructions/sync');
}

export function getPlaybooks() {
  return get('/playbooks');
}
