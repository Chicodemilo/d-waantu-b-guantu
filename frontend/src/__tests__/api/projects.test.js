// Path: src/__tests__/api/projects.test.js
// File: projects.test.js
// Created: 2026-03-29
// Purpose: Unit tests for the projects API module (CRUD, deployPlaybooks)
// Caller: vitest test runner
// Callees: ../../api/projects (getProjects, getProject, createProject, updateProject, deleteProject, deployPlaybooks)
// Data In: Mock fetch responses
// Data Out: Test assertions
// Last Modified: 2026-06-12

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getProjects,
  getProject,
  createProject,
  updateProject,
  deleteProject,
  deployPlaybooks,
} from '../../api/projects';

const mockFetch = vi.fn();
global.fetch = mockFetch;

function jsonResponse(data, status = 200) {
  const body = data === undefined ? '' : JSON.stringify(data);
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(body),
  });
}

function noContentResponse() {
  return Promise.resolve({
    ok: true,
    status: 204,
    json: () => Promise.reject(new Error('No content')),
    text: () => Promise.resolve(''),
  });
}

beforeEach(() => mockFetch.mockReset());


describe('getProjects()', () => {
  it('calls GET /projects', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getProjects();
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/projects');
  });
});


describe('getProject()', () => {
  it('calls GET /projects/:id', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1 }));
    await getProject(1);
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/projects/1');
  });
});


describe('createProject()', () => {
  it('calls POST /projects', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1 }, 201));
    await createProject({ prefix: 'TST', name: 'Test' });
    const [url, config] = mockFetch.mock.calls[0];
    expect(config.method).toBe('POST');
    expect(JSON.parse(config.body)).toEqual({ prefix: 'TST', name: 'Test' });
  });
});


describe('updateProject()', () => {
  it('calls PATCH /projects/:id', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1 }));
    await updateProject(1, { name: 'Updated' });
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/projects/1');
    expect(config.method).toBe('PATCH');
  });
});


describe('deleteProject()', () => {
  it('calls DELETE /projects/:id', async () => {
    mockFetch.mockReturnValue(noContentResponse());
    await deleteProject(1);
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/projects/1');
    expect(config.method).toBe('DELETE');
  });
});


describe('deployPlaybooks()', () => {
  it('calls POST /projects/:id/deploy-playbooks', async () => {
    const mockData = { deployed: ['team_lead_playbook.md'], target_dir: '/tmp/.claude' };
    mockFetch.mockReturnValue(jsonResponse(mockData));
    const result = await deployPlaybooks(1);
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/projects/1/deploy-playbooks');
    expect(config.method).toBe('POST');
    expect(result).toEqual(mockData);
  });
});
