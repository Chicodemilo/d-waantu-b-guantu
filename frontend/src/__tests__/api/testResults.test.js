// Path: src/__tests__/api/testResults.test.js
// File: testResults.test.js
// Created: 2026-03-29
// Purpose: Unit tests for the testResults API module (getTestRuns, getTestRun)
// Caller: vitest test runner
// Callees: ../../api/testResults (getTestRuns, getTestRun)
// Data In: Mock fetch responses
// Data Out: Test assertions
// Last Modified: 2026-06-12

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getTestRuns, getTestRun } from '../../api/testResults';

const mockFetch = vi.fn();
global.fetch = mockFetch;

function jsonResponse(data, status = 200) {
  const body = data === undefined ? '' : JSON.stringify(data);
  return Promise.resolve({
    ok: true,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(body),
  });
}

beforeEach(() => mockFetch.mockReset());


describe('getTestRuns()', () => {
  it('calls GET /test-results', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    const result = await getTestRuns();
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/test-results');
    expect(result).toEqual([]);
  });

  it('passes query params', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getTestRuns({ project_id: 1, suite: 'backend' });
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain('project_id=1');
    expect(url).toContain('suite=backend');
  });
});


describe('getTestRun()', () => {
  it('calls GET /test-results/:id', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 5 }));
    const result = await getTestRun(5);
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/test-results/5');
    expect(result).toEqual({ id: 5 });
  });
});
