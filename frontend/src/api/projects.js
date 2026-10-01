// Path: src/api/projects.js
// File: projects.js
// Created: 2026-03-29
// Purpose: CRUD API functions for projects plus deploy-playbooks, create-from-repo, and the DWB-596 memory-transition status read
// Caller: pages/DashboardPage.jsx, pages/ProjectPage.jsx, hooks/useProjectsData.js, hooks/useAppData.js
// Callees: ./client (get, post, patch, del)
// Data In: Project ID for fetch/update/delete/actions; project data for create/update; repo path for create-from-repo
// Data Out: Project objects/arrays, action responses from /projects endpoint
// Last Modified: 2026-09-30 (DWB-597: getMemoryTransition)

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

// DWB-596/597: derived status of the project's open memory-mode transition.
// Callers must only reach for this when project.memory_mode is a transition
// state; a project that never started one is answered by memory_mode alone and
// must not produce a request. When there is no open run the fields come back
// null rather than as a 404, so the normal case needs no try/catch.
export function getMemoryTransition(id, options = {}) {
  return get(`/projects/${id}/memory-transition`, {}, options);
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

export function getPlaybookFiles(id) {
  return get(`/projects/${id}/playbook-files`);
}

export function getGateStatus(id) {
  return get(`/projects/${id}/gate-status`);
}
