import { get, post, patch, del } from './client';

export function getTickets(params = {}) {
  return get('/tickets', params);
}

export function getTicket(id) {
  return get(`/tickets/${id}`);
}

export function createTicket(data) {
  return post('/tickets', data);
}

export function updateTicket(id, data) {
  return patch(`/tickets/${id}`, data);
}

export function deleteTicket(id) {
  return del(`/tickets/${id}`);
}

export function getTicketHistory(id) {
  return get(`/tickets/${id}/history`);
}
