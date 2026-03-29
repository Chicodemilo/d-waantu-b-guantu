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
