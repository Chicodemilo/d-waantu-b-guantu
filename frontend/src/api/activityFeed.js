// Path: src/api/activityFeed.js
// File: activityFeed.js
// Created: 2026-03-29
// Purpose: API function to fetch live activity feed for a project
// Caller: components/project/ActivityFeed.jsx
// Callees: ./client (get)
// Data In: Project ID, optional limit
// Data Out: Array of {id, action, entity_type, entity_id, details, agent_name, created_at}
// Last Modified: 2026-03-29

import { get } from './client';

export function getActivityFeed(projectId, limit = 50) {
  return get(`/projects/${projectId}/activity-feed`, { limit });
}
