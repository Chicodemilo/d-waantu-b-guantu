// Path: src/__tests__/TokenBudgetMemory.test.jsx
// File: TokenBudgetMemory.test.jsx
// Created: 2026-06-19
// Purpose: Tests for DWB-401 TokenBudget memory grouping. Verifies the Memory section collapses to the 2-file model (identity.md + memory.md via the memory_main category), excludes retired sub-category files, subgroups by agent, and shows the updated 2-file tooltip copy.
// Caller: vitest test runner
// Callees: ../components/project/TokenBudget, global fetch (stubbed)
// Data In: Stubbed token-budget fetch response
// Data Out: Test assertions
// Last Modified: 2026-06-19

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import TokenBudget from '../components/project/TokenBudget';

function budget(files) {
  return {
    total_tokens: files.reduce((a, f) => a + f.tokens, 0),
    team_startup_cost: 12000,
    files,
  };
}

function memFile(name, category, overrides = {}) {
  return {
    path: `/repo/.dwb/memory/DWB/Freddie/${name}`,
    name,
    category,
    agent_name: 'Freddie',
    tokens: 1000,
    ceiling: 4500,
    status: 'ok',
    ...overrides,
  };
}

function stubFetch(data) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(data) }))
  );
}

async function renderExpanded(data) {
  stubFetch(data);
  render(<TokenBudget projectId={1} />);
  // Component renders null while loading; wait for the toggle, then expand.
  const toggle = await screen.findByRole('button', { name: /token budget/i });
  fireEvent.click(toggle);
}

describe('TokenBudget memory grouping (DWB-401)', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders the 2-file memory model (identity.md + memory.md) under the agent subgroup', async () => {
    await renderExpanded(
      budget([
        memFile('identity.md', 'memory_identity', { tokens: 400, ceiling: 600 }),
        memFile('memory.md', 'memory_main', { tokens: 1200, ceiling: 4500 }),
      ])
    );
    await waitFor(() => {
      expect(screen.getByText('memory.md')).toBeInTheDocument();
    });
    expect(screen.getByText('identity.md')).toBeInTheDocument();
    // subgroupBy: 'agent_name' still groups under the agent.
    expect(screen.getByText('Freddie')).toBeInTheDocument();
  });

  it('excludes retired memory sub-category files (scratchpad/lessons/recent)', async () => {
    await renderExpanded(
      budget([
        memFile('identity.md', 'memory_identity', { tokens: 400, ceiling: 600 }),
        memFile('memory.md', 'memory_main', { tokens: 1200, ceiling: 4500 }),
        // Stale rows under old keys must NOT render anymore.
        memFile('scratchpad.md', 'memory_scratchpad'),
        memFile('lessons.md', 'memory_lessons'),
        memFile('recent_sessions.md', 'memory_recent'),
      ])
    );
    await waitFor(() => {
      expect(screen.getByText('memory.md')).toBeInTheDocument();
    });
    expect(screen.queryByText('scratchpad.md')).not.toBeInTheDocument();
    expect(screen.queryByText('lessons.md')).not.toBeInTheDocument();
    expect(screen.queryByText('recent_sessions.md')).not.toBeInTheDocument();
  });

  it('shows the updated 2-file tooltip copy', async () => {
    await renderExpanded(
      budget([memFile('memory.md', 'memory_main', { tokens: 1200, ceiling: 4500 })])
    );
    await waitFor(() => {
      expect(screen.getByText(/single free-form memory/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/the owning agent writes memory\.md/i)).toBeInTheDocument();
  });
});
