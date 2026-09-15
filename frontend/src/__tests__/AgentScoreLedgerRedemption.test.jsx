// Path: src/__tests__/AgentScoreLedgerRedemption.test.jsx
// File: AgentScoreLedgerRedemption.test.jsx
// Created: 2026-09-15
// Purpose: DWB-537: the per-agent score ledger renders a `redemption` trigger row with the plain "redemption" label, a positive delta, and its auto source.
// Caller: vitest test runner
// Callees: ../components/agents/AgentScoreLedger, ../api/scores (mocked)
// Data In: Mocked getAgentScore payload with one stick and one redemption row
// Data Out: Test assertions
// Last Modified: 2026-09-15 (DWB-537)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

vi.mock('../api/scores', () => ({
  getAgentScore: vi.fn(),
}));

import AgentScoreLedger from '../components/agents/AgentScoreLedger';
import { getAgentScore } from '../api/scores';

const payload = {
  agent_id: 21,
  project_id: 1,
  reputation: -3,
  influence: 20,
  sprint_delta: -3,
  rank: 2,
  tier: null,
  ledger: [
    {
      id: 2, delta: 3, source: 'auto', trigger_type: 'redemption',
      reason: 'redeemed stick #1 via memory note', actor_agent_id: null,
      actor_name: null, actor_cost: 0, ref_type: 'score_event', ref_id: 1,
      reverted_by: null, sprint_id: 160, created_at: '2026-09-15T12:00:00',
    },
    {
      id: 1, delta: -6, source: 'human', trigger_type: 'stick',
      reason: 'missed heads', actor_agent_id: null, actor_name: null,
      actor_cost: 0, ref_type: null, ref_id: null, reverted_by: null,
      sprint_id: 160, created_at: '2026-09-15T11:00:00',
    },
  ],
};

beforeEach(() => {
  getAgentScore.mockReset();
  getAgentScore.mockResolvedValue(payload);
});

afterEach(() => {
  cleanup();
});

describe('AgentScoreLedger redemption row (DWB-537)', () => {
  it('renders the redemption trigger label with its positive delta', async () => {
    render(<AgentScoreLedger agentId={21} projectId={1} />);
    const trigger = await screen.findByText('redemption', { exact: false, selector: '.score-ledger__col-trigger' });
    expect(trigger).toBeInTheDocument();
    expect(trigger.textContent).toContain('auto');
    expect(screen.getByText('+3')).toHaveClass('score-ledger__delta--up');
    expect(screen.getByText('redeemed stick #1 via memory note')).toBeInTheDocument();
  });
});
