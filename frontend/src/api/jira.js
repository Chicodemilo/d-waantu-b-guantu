// Path: src/api/jira.js
// File: jira.js
// Created: 2026-05-27
// Purpose: API wrappers for the /api/jira/* live proxy endpoints (read-only Jira data) plus DWB-342's three project-scoped snapshot endpoints (cached Jira table + manual sync trigger + sync-status poll)
// Caller: pages/JiraIssuesPage.jsx, components/tickets/TicketList.jsx (badge), store/useStore.js (jira slice)
// Callees: ./client (get, post)
// Data In: Issue key, JQL string, project key, sprint id, project_id for snapshot endpoints
// Data Out: Normalized issue / sprint / project dicts; snapshot row arrays

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

// getJiraRollup removed in DWB-342 — JiraRollupPage was deleted as part of
// the unification (single Jira nav link, single table). Backend /jira/rollup
// endpoint may still exist; no frontend caller.

// ---- DWB-342: snapshot-backed project Jira table ----

export function getProjectJiraTickets(projectId, params = {}) {
  return get(`/projects/${projectId}/jira-tickets`, params);
}

export function triggerProjectJiraSync(projectId) {
  return post(`/projects/${projectId}/jira-sync`);
}

export function getProjectJiraSyncStatus(projectId) {
  return get(`/projects/${projectId}/jira-sync/status`);
}
