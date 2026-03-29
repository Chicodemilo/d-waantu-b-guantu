// Path: src/api/tickets.js
// File: tickets.js
// Created: 2026-03-29
// Purpose: CRUD API functions for tickets plus ticket history retrieval
// Caller: hooks/useTicketsData.js, hooks/useAppData.js, components/tickets/TicketDetail.jsx
// Callees: ./client (get, post, patch, del)
// Data In: Ticket ID for fetch/update/delete/history; ticket data for create/update; query params for listing
// Data Out: Ticket objects/arrays, ticket history array from /tickets endpoint
// Last Modified: 2026-03-29

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
