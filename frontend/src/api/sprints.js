import { get, post, patch, del } from './client';

export function getSprints(params = {}) {
  return get('/sprints', params);
}

export function getSprint(id) {
  return get(`/sprints/${id}`);
}

export function createSprint(data) {
  return post('/sprints', data);
}

export function updateSprint(id, data) {
  return patch(`/sprints/${id}`, data);
}

export function deleteSprint(id) {
  return del(`/sprints/${id}`);
}
