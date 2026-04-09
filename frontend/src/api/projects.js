// Path: src/api/projects.js
// File: projects.js
// Created: 2026-03-29
// Purpose: CRUD API functions for projects plus deploy-playbooks and create-from-repo actions
// Caller: pages/DashboardPage.jsx, pages/ProjectPage.jsx, hooks/useProjectsData.js, hooks/useAppData.js
// Callees: ./client (get, post, patch, del)
// Data In: Project ID for fetch/update/delete/actions; project data for create/update; repo path for create-from-repo
// Data Out: Project objects/arrays, action responses from /projects endpoint
// Last Modified: 2026-03-29

import { get, post, patch, del } from './client';

export function getProjects(params = {}) {
  return get('/projects', params);
}

export function getProject(id) {
  return get(`/projects/${id}`);
}

export function createProject(data) {
  return post('/projects', data);
}

export function updateProject(id, data) {
  return patch(`/projects/${id}`, data);
}

export function deleteProject(id) {
  return del(`/projects/${id}`);
}

export function deployPlaybooks(id) {
  return post(`/projects/${id}/deploy-playbooks`);
}

export function createProjectFromRepo(repoPath) {
  return post('/projects/from-repo', { repo_path: repoPath });
}

export function seedDemoProject() {
  return post('/projects/seed-demo');
}

export function disableJira(id) {
  return post(`/projects/${id}/disable-jira`);
}
