// Path: src/api/epics.js
// File: epics.js
// Created: 2026-03-29
// Purpose: CRUD API functions for epic entities
// Caller: hooks/useEpicsData.js, hooks/useAppData.js
// Callees: ./client (get, post, patch, del)
// Data In: Epic ID for single fetch/update/delete; epic data object for create/update; query params for listing
// Data Out: Epic objects or arrays from the /epics endpoint
// Last Modified: 2026-03-29

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
