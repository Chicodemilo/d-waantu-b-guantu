// Path: src/components/agents/__tests__/AgentMemoryPanel.test.jsx
// File: AgentMemoryPanel.test.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: Tests for the per-agent human_memory panel. Covers the
//          not-computed states (stock mode, unscoped agent), grouping
//          scored entries by tier, the unscored/untiered section, and the
//          demote/evict/promote summary counts.
// Caller: vitest test runner
// Callees: ../AgentMemoryPanel, ../../../api/memory (mocked)
// Data In: Mocked getScoredMemory responses
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-613)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';

vi.mock('../../../api/memory', () => ({
  getScoredMemory: vi.fn(),
}));

import AgentMemoryPanel from '../AgentMemoryPanel';
import { getScoredMemory } from '../../../api/memory';

beforeEach(() => {
  getScoredMemory.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('AgentMemoryPanel (DWB-613)', () => {
  it('shows a not-computed message for a stock-mode project', async () => {
    getScoredMemory.mockResolvedValue({
      agent_id: 1, computed: false, reason: 'project_not_in_human_memory_mode',
      memory_mode: 'stock', entries: [], demote: [], evict: [], promote: [],
    });
    render(<AgentMemoryPanel agentId={1} />);

    expect(await screen.findByText(/stock memory, not human_memory/)).toBeInTheDocument();
  });

  it('groups scored entries by tier and shows score + band', async () => {
    getScoredMemory.mockResolvedValue({
      agent_id: 1, computed: true, reason: null, memory_mode: 'human_memory',
      entries: [
        { id: 1, tier: 'core', body: 'never guess a peer contract', context_key: null, fired_count: 2, scored: true, reason: null, sessions_since_reinforced: 3, score: 10, band: 'full_text' },
        { id: 2, tier: 'working', body: 'a stale lesson', context_key: null, fired_count: 0, scored: true, reason: null, sessions_since_reinforced: 20, score: 4, band: 'demotion_candidate' },
        { id: 3, tier: 'raw', body: 'fresh, unjudged', context_key: null, fired_count: 0, scored: false, reason: 'untiered', sessions_since_reinforced: null, score: null, band: null },
      ],
      demote: [2], evict: [], promote: [7],
    });
    render(<AgentMemoryPanel agentId={1} />);

    const coreTable = await screen.findByTestId('memory-tier-core');
    expect(within(coreTable).getByText('never guess a peer contract')).toBeInTheDocument();
    expect(within(coreTable).getByText('10')).toBeInTheDocument();
    expect(within(coreTable).getByText('full text')).toBeInTheDocument();

    const workingTable = screen.getByTestId('memory-tier-working');
    expect(within(workingTable).getByText('demotion candidate')).toBeInTheDocument();

    const unscoredTable = screen.getByTestId('memory-tier-unscored');
    expect(within(unscoredTable).getByText('awaiting consolidation')).toBeInTheDocument();

    expect(screen.getByTestId('memory-demote-count')).toHaveTextContent('1');
    expect(screen.getByTestId('memory-evict-count')).toHaveTextContent('0');
    expect(screen.getByTestId('memory-promote-count')).toHaveTextContent('1');
  });

  it('shows a clean empty state when computed but no memories exist', async () => {
    getScoredMemory.mockResolvedValue({
      agent_id: 1, computed: true, reason: null, memory_mode: 'human_memory',
      entries: [], demote: [], evict: [], promote: [],
    });
    render(<AgentMemoryPanel agentId={1} />);

    expect(await screen.findByText('No memories yet')).toBeInTheDocument();
  });
});
