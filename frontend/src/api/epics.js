import { get, post, patch, del } from './client';

export function getEpics(params = {}) {
  return get('/epics', params);
}

export function getEpic(id) {
  return get(`/epics/${id}`);
}

export function createEpic(data) {
  return post('/epics', data);
}

export function updateEpic(id, data) {
  return patch(`/epics/${id}`, data);
}

export function deleteEpic(id) {
  return del(`/epics/${id}`);
}
