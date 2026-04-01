// Path: src/config.js
// File: config.js
// Created: 2026-03-29
// Purpose: Central configuration constants for API base URL, polling intervals, log limits, and role definitions
// Caller: api/client.js, store/useStore.js, hooks/usePolling.js, hooks/useActivityData.js, hooks/useAppData.js, components/dashboard/TokenOverview.jsx
// Callees: None (leaf config module; reads from import.meta.env)
// Data In: VITE_API_BASE_URL, VITE_POLL_ACTIVE_MS environment variables (optional)
// Data Out: API_BASE_URL, POLLING_ACTIVE_INTERVAL, POLLING_IDLE_INTERVAL, ACTIVITY_LOG_LIMIT, ROLES
// Last Modified: 2026-03-29

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

export const POLLING_ACTIVE_INTERVAL = Number(import.meta.env.VITE_POLL_ACTIVE_MS) || 4000;
export const POLLING_IDLE_INTERVAL = 10000;

export const ACTIVITY_LOG_LIMIT = 50;

export const ROLES = {
  TEAM_LEAD: 'team-lead',
  PM: 'pm',
};
