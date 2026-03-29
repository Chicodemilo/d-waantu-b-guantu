// Path: src/api/sprints.js
// File: sprints.js
// Created: 2026-03-29
// Purpose: CRUD API functions for sprint entities
// Caller: hooks/useSprintsData.js, hooks/useAppData.js
// Callees: ./client (get, post, patch, del)
// Data In: Sprint ID for single fetch/update/delete; sprint data object for create/update; query params for listing
// Data Out: Sprint objects or arrays from the /sprints endpoint
// Last Modified: 2026-03-29

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
