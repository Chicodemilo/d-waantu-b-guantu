// Path: src/api/jira.js
// File: jira.js
// Created: 2026-05-27
// Purpose: API wrappers for the /api/jira/* proxy endpoints (read-only Jira data)
// Caller: pages/JiraIssuesPage.jsx, components/tickets/TicketList.jsx (badge), store/useStore.js (jira slice)
// Callees: ./client (get, post)
// Data In: Issue key, JQL string, project key, sprint id
// Data Out: Normalized issue / sprint / project dicts

import { get, post } from './client';

export function getJiraConfig() {
  return get('/jira/config');
}

export function listJiraProjects() {
  return get('/jira/projects');
}

export function getJiraIssue(issueKey) {
  return get(`/jira/issues/${issueKey}`);
}

export function searchJiraIssues(jql, limit = 50) {
  return get('/jira/search', { jql, limit });
}

export function listActiveSprints(projectKey) {
  return get(`/jira/projects/${projectKey}/sprints`);
}

export function listSprintIssues(sprintId) {
  return get(`/jira/sprints/${sprintId}/issues`);
}

export function clearJiraCache() {
  return post('/jira/cache/clear');
}

export function syncFromJira(projectId = null) {
  const qs = projectId != null ? `?project_id=${projectId}` : '';
  return post(`/jira/sync${qs}`);
}

export function getJiraRollup(projectId) {
  return get('/jira/rollup', { project_id: projectId });
}
