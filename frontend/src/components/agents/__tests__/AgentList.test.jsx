// Path: src/components/agents/__tests__/AgentList.test.jsx
// File: AgentList.test.jsx
// Created: 2026-06-23
// Purpose: Tests for the dashboard Agents table (DWB-460, reputation join from DWB-435). Covers per-(project, agent) reputation joined from getProjectScores, defaulting to 0 when an agent is absent, one row per project_agent entry, the Project/Agent/Role/Rep/Status/Description columns, and default sort by reputation descending.
// Caller: vitest test runner
// Callees: ../AgentList, ../../../store/useStore (mocked), ../../../api/scores (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store state + mocked getProjectScores
// Data Out: Test assertions
// Last Modified: 2026-06-24

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../api/scores', () => ({
  getProjectScores: vi.fn(),
}));

let mockState;
vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import AgentList from '../AgentList';
import { getProjectScores } from '../../../api/scores';

function seed() {
  mockState = {
    agents: [
      { id: 19, name: 'Freddie', role: 'frontend-worker', description: 'FE', is_active: true },
      { id: 21, name: 'Barry', role: 'backend-worker', description: 'BE', is_active: false },
    ],
    projectAgents: [
      { project_id: 1, agent_id: 19 },
      { project_id: 1, agent_id: 21 },
    ],
    projects: [
      { id: 1, prefix: 'DWB', status: 'active' },
    ],
  };
}

beforeEach(() => {
  getProjectScores.mockReset();
  seed();
});

afterEach(() => {
  cleanup();
});

function renderList() {
  return render(
    <MemoryRouter>
      <AgentList />
    </MemoryRouter>
  );
}

// Returns the agent name in each data row, top to bottom (header row excluded).
function bodyRowNames() {
  const rows = screen.getAllByRole('row');
  // row[0] is the sticky header; data rows follow.
  return rows.slice(1).map((r) => within(r).getAllByRole('cell')[1].textContent);
}

describe('AgentList table (DWB-460)', () => {
  it('renders the Project/Agent/Role/Rep/Status/Description columns', async () => {
    getProjectScores.mockResolvedValue([]);
    renderList();
    await waitFor(() => expect(getProjectScores).toHaveBeenCalledWith(1));
    for (const label of ['Project', 'Agent', 'Role', 'Rep', 'Status', 'Description']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(`^${label}`) })).toBeInTheDocument();
    }
  });

  it('joins each agent reputation from the project scores and shows it as a number', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', reputation: 6, sprint_delta: 6, influence: 20 },
      { agent_id: 21, agent_name: 'Barry', reputation: 35, sprint_delta: 35, influence: 20 },
    ]);
    renderList();

    await waitFor(() => expect(screen.getByText('35')).toBeInTheDocument());
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(getProjectScores).toHaveBeenCalledWith(1);
  });

  it('defaults reputation to 0 when an agent is absent from the scores payload', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', reputation: 6, sprint_delta: 6, influence: 20 },
    ]);
    renderList();

    await waitFor(() => expect(screen.getByText('6')).toBeInTheDocument());
    // Barry has no score row -> defaults to 0
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('renders 0 for every agent when the scores fetch fails', async () => {
    getProjectScores.mockRejectedValue(new Error('boom'));
    renderList();

    await waitFor(() => expect(screen.getAllByText('0')).toHaveLength(2));
  });

  it('defaults to sorting by reputation descending (high to low)', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', reputation: 6, sprint_delta: 6, influence: 20 },
      { agent_id: 21, agent_name: 'Barry', reputation: 35, sprint_delta: 35, influence: 20 },
    ]);
    renderList();

    await waitFor(() => expect(screen.getByText('35')).toBeInTheDocument());
    // Barry (35) outranks Freddie (6), so Barry's row comes first.
    expect(bodyRowNames()).toEqual(['Barry', 'Freddie']);
  });
});
