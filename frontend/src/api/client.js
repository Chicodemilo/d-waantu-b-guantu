// Path: src/api/client.js
// File: client.js
// Created: 2026-03-29
// Purpose: Core HTTP client wrapping fetch with error handling for API requests (get, post, patch, del)
// Caller: All api/ modules (agents, projects, tickets, sprints, epics, alerts, etc.), client.test.js
// Callees: ../config (API_BASE_URL)
// Data In: URL path strings, query params objects, request body data
// Data Out: Parsed JSON responses; throws ApiError on non-OK responses
// Last Modified: 2026-03-29

import { API_BASE_URL } from '../config';

const BASE_URL = API_BASE_URL;

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const config = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {}
    throw new ApiError(
      data?.detail || `Request failed: ${response.status}`,
      response.status,
      data
    );
  }

  if (response.status === 204) return null;

  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export function get(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null) query.set(key, value);
  }
  const qs = query.toString();
  return request(qs ? `${path}?${qs}` : path);
}

export function post(path, data) {
  return request(path, { method: 'POST', body: JSON.stringify(data) });
}

export function patch(path, data) {
  return request(path, { method: 'PATCH', body: JSON.stringify(data) });
}

export function del(path) {
  return request(path, { method: 'DELETE' });
}

export { ApiError };
