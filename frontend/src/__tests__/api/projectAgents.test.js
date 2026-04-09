// Path: src/__tests__/api/projectAgents.test.js
// File: projectAgents.test.js
// Created: 2026-03-29
// Purpose: Unit tests for the projectAgents API module (getProjectAgents)
// Caller: vitest test runner
// Callees: ../../api/projectAgents (getProjectAgents)
// Data In: Mock fetch responses
// Data Out: Test assertions
// Last Modified: 2026-04-09

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getProjectAgents } from '../../api/projectAgents';

const mockFetch = vi.fn();
global.fetch = mockFetch;

function jsonResponse(data, status = 200) {
  return Promise.resolve({
    ok: true,
    status,
    json: () => Promise.resolve(data),
  });
}

beforeEach(() => mockFetch.mockReset());


describe('getProjectAgents()', () => {
  it('calls GET /project-agents', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    const result = await getProjectAgents();
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/project-agents');
    expect(result).toEqual([]);
  });

  it('passes query params', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getProjectAgents({ project_id: 1 });
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain('project_id=1');
  });
});
