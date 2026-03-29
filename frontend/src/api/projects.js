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

export function scanTokens(id) {
  return post(`/projects/${id}/scan-tokens`);
}
