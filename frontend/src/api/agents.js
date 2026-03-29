// Path: src/api/agents.js
// File: agents.js
// Created: 2026-03-29
// Purpose: CRUD API functions for agent entities
// Caller: hooks/useAgentsData.js, hooks/useAppData.js
// Callees: ./client (get, post, patch, del)
// Data In: Agent ID for single fetch/update/delete; agent data object for create/update; query params for listing
// Data Out: Agent objects or arrays from the /agents endpoint
// Last Modified: 2026-03-29

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
