import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getInstructions,
  getInstruction,
  createInstruction,
  updateInstruction,
  deleteInstruction,
  syncCheck,
  syncInstructions,
  getPlaybooks,
} from '../../api/instructions';

const mockFetch = vi.fn();
global.fetch = mockFetch;

function jsonResponse(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  });
}

function noContentResponse() {
  return Promise.resolve({
    ok: true,
    status: 204,
    json: () => Promise.reject(new Error('No content')),
  });
}

beforeEach(() => mockFetch.mockReset());


describe('getInstructions()', () => {
  it('calls GET /instructions', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getInstructions();
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/instructions');
  });

  it('passes filter params', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getInstructions({ scope: 'global', project_id: 1 });
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain('scope=global');
    expect(url).toContain('project_id=1');
  });
});


describe('getInstruction()', () => {
  it('calls GET /instructions/:id', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 3 }));
    const result = await getInstruction(3);
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/instructions/3');
    expect(result.id).toBe(3);
  });
});


describe('createInstruction()', () => {
  it('calls POST /instructions', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1 }, 201));
    await createInstruction({ scope: 'global', title: 'T', body: 'B' });
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/instructions');
    expect(config.method).toBe('POST');
    expect(JSON.parse(config.body)).toEqual({ scope: 'global', title: 'T', body: 'B' });
  });
});


describe('updateInstruction()', () => {
  it('calls PATCH /instructions/:id', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1, title: 'Updated' }));
    await updateInstruction(1, { title: 'Updated' });
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/instructions/1');
    expect(config.method).toBe('PATCH');
  });
});


describe('deleteInstruction()', () => {
  it('calls DELETE /instructions/:id', async () => {
    mockFetch.mockReturnValue(noContentResponse());
    const result = await deleteInstruction(1);
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/instructions/1');
    expect(config.method).toBe('DELETE');
    expect(result).toBeNull();
  });
});


describe('syncCheck()', () => {
  it('calls GET /instructions/sync-check', async () => {
    const mockData = { matched: [], memory_only: [], db_only: [], in_sync: true };
    mockFetch.mockReturnValue(jsonResponse(mockData));
    const result = await syncCheck();
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/instructions/sync-check');
    expect(result).toEqual(mockData);
  });
});


describe('syncInstructions()', () => {
  it('calls POST /instructions/sync', async () => {
    mockFetch.mockReturnValue(jsonResponse([], 201));
    const result = await syncInstructions();
    const [url, config] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/instructions/sync');
    expect(config.method).toBe('POST');
    expect(result).toEqual([]);
  });
});


describe('getPlaybooks()', () => {
  it('calls GET /playbooks', async () => {
    const mockData = [{ name: 'team_lead', title: 'TL Playbook', content: '# TL' }];
    mockFetch.mockReturnValue(jsonResponse(mockData));
    const result = await getPlaybooks();
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/playbooks');
    expect(result).toEqual(mockData);
  });
});
