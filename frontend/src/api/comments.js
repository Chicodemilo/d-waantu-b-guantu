// Path: src/api/comments.js
// File: comments.js
// Created: 2026-03-29
// Purpose: API functions for fetching, creating, and deleting comments
// Caller: hooks/useAppData.js, hooks/useCommentsData.js
// Callees: ./client (get, post, del)
// Data In: Comment ID for fetch/delete; comment data object for creation; query params for listing
// Data Out: Comment objects or arrays from the /comments endpoint
// Last Modified: 2026-03-29

import { get, post, del } from './client';

export function getComments(params = {}) {
  return get('/comments', params);
}

export function getComment(id) {
  return get(`/comments/${id}`);
}

export function createComment(data) {
  return post('/comments', data);
}

export function deleteComment(id) {
  return del(`/comments/${id}`);
}
