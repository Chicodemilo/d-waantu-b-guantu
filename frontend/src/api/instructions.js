// Path: src/api/instructions.js
// File: instructions.js
// Created: 2026-03-29
// Purpose: CRUD API functions for instructions plus sync-check, sync, and playbook retrieval
// Caller: pages/InstructionsPage.jsx, hooks/useAppData.js, hooks/useInstructionsData.js
// Callees: ./client (get, post, patch, del)
// Data In: Instruction ID for fetch/update/delete; instruction data for create/update; no params for sync/playbooks
// Data Out: Instruction objects/arrays, sync status, playbook arrays
// Last Modified: 2026-03-29

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
