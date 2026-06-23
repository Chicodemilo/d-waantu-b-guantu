// Path: src/components/agents/__tests__/AgentScoreLedger.test.jsx
// File: AgentScoreLedger.test.jsx
// Created: 2026-06-23
// Purpose: Tests for the rank + tier summary tiles on the AgentPage score panel (DWB-434 part 2). Covers rendering rank (#N) and the mapped tier label from the agent-detail endpoint, and graceful "-" fall-back when those fields are absent.
// Caller: vitest test runner
// Callees: ../AgentScoreLedger, ../../../api/scores (mocked)
// Data In: Mocked getAgentScore responses
// Data Out: Test assertions
// Last Modified: 2026-06-23

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';

vi.mock('../../../api/scores', () => ({
  getAgentScore: vi.fn(),
}));

import AgentScoreLedger from '../AgentScoreLedger';
import { getAgentScore } from '../../../api/scores';

beforeEach(() => {
  getAgentScore.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('AgentScoreLedger rank + tier (DWB-434 part 2)', () => {
  it('renders rank as #N and the mapped tier label', async () => {
    getAgentScore.mockResolvedValue({
      agent_id: 21, project_id: 1, reputation: 41, influence: 20, sprint_delta: 41,
      rank: 1, tier: 'best', ledger: [],
    });
    render(<AgentScoreLedger agentId={21} projectId={1} />);

    expect(await screen.findByText('#1')).toBeInTheDocument();
    expect(screen.getByText('TOP')).toBeInTheDocument();
    expect(screen.getByText('Rank')).toBeInTheDocument();
    expect(screen.getByText('Tier')).toBeInTheDocument();
  });

  it('falls back to "-" when rank and tier are absent', async () => {
    getAgentScore.mockResolvedValue({
      agent_id: 19, project_id: 1, reputation: 6, influence: 20, sprint_delta: 6,
      ledger: [],
    });
    render(<AgentScoreLedger agentId={19} projectId={1} />);

    await screen.findByText('Rank');
    // Both rank and tier tiles show the dash placeholder.
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(2);
  });
});
