// Path: src/__tests__/api/scores.test.js
// File: scores.test.js
// Created: 2026-06-22
// Purpose: Unit tests for the scores API module (getProjectScores, getAgentScore)
// Caller: vitest test runner
// Callees: ../../api/scores (getProjectScores, getAgentScore)
// Data In: Mock fetch responses
// Data Out: Test assertions
// Last Modified: 2026-06-22

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getProjectScores, getAgentScore } from '../../api/scores';

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

describe('getProjectScores()', () => {
  it('calls GET /projects/:id/scores', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    const result = await getProjectScores(1);
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/api/projects/1/scores');
    expect(result).toEqual([]);
  });
});

describe('getAgentScore()', () => {
  it('calls GET /agents/:id/score with project_id query', async () => {
    mockFetch.mockReturnValue(jsonResponse({ agent_id: 19, ledger: [] }));
    await getAgentScore(19, 1);
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain('/agents/19/score');
    expect(url).toContain('project_id=1');
  });
});
