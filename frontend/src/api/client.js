// Path: src/api/client.js
// File: client.js
// Created: 2026-03-29
// Purpose: Core HTTP client wrapping fetch with error handling for API requests (get, post, patch, del). Each verb accepts an optional { signal } AbortController signal to support cancellation on component unmount (DWB-370). Each request is instrumented with fetch-lifecycle logs (start/end/abort/fail) via services/logger so the TL can see the live trail at /api/client-logs (DWB-371).
// Caller: All api/ modules (agents, projects, tickets, sprints, epics, alerts, etc.), client.test.js
// Callees: ../config (API_BASE_URL), ../services/logger (log)
// Data In: URL path strings, query params objects, request body data, optional { signal } option
// Data Out: Parsed JSON responses; throws ApiError on non-OK responses; AbortError on cancelled requests
// Last Modified: 2026-06-10

import { API_BASE_URL } from '../config';
import { log } from '../services/logger';

const BASE_URL = API_BASE_URL;

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

function reportError(path, method, status, message, stack) {
  try {
    fetch(`${BASE_URL}/errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'frontend',
        endpoint: `${method} ${path}`,
        error_type: status ? `HTTP_${status}` : 'NetworkError',
        message: (message || 'Unknown error').slice(0, 2000),
        stack_trace: (stack || '').slice(0, 10000),
        status_code: status || null,
      }),
    }).catch(() => {});
  } catch {}
}

function nowMs() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const method = (options.method || 'GET').toUpperCase();
  const config = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };

  const t0 = nowMs();
  log.debug('fetch', `${method} ${path}`, { start: t0 });

  let response;
  try {
    response = await fetch(url, config);
  } catch (err) {
    const ms = Math.round(nowMs() - t0);
    if (err.name === 'AbortError') {
      log.debug('fetch.abort', `${method} ${path}`, { ms });
    } else {
      log.warn('fetch.fail', `${method} ${path}: ${err.message}`, { ms });
      reportError(path, method, null, err.message, err.stack);
    }
    throw err;
  }

  const ms = Math.round(nowMs() - t0);
  log.info('fetch', `${method} ${path} ${response.status} ${ms}ms`, { status: response.status, ms });

  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {}
    const message = data?.detail || `Request failed: ${response.status}`;
    const error = new ApiError(message, response.status, data);
    reportError(path, method, response.status, message, error.stack);
    throw error;
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

export function get(path, params = {}, options = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null) query.set(key, value);
  }
  const qs = query.toString();
  return request(qs ? `${path}?${qs}` : path, { signal: options.signal });
}

export function post(path, data, options = {}) {
  return request(path, { method: 'POST', body: JSON.stringify(data), signal: options.signal });
}

export function patch(path, data, options = {}) {
  return request(path, { method: 'PATCH', body: JSON.stringify(data), signal: options.signal });
}

export function del(path, options = {}) {
  return request(path, { method: 'DELETE', signal: options.signal });
}

export { ApiError };
