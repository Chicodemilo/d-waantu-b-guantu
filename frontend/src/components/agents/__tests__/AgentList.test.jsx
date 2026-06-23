// Path: src/components/agents/__tests__/AgentList.test.jsx
// File: AgentList.test.jsx
// Created: 2026-06-23
// Purpose: Tests for the dashboard Agents list reputation badge (DWB-435). Covers joining per-(project, agent) reputation from getProjectScores by project, defaulting to 0 when an agent is absent from a project's scores, and rendering one card per project_agent entry.
// Caller: vitest test runner
// Callees: ../AgentList, ../../../store/useStore (mocked), ../../../api/scores (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store state + mocked getProjectScores
// Data Out: Test assertions
// Last Modified: 2026-06-23

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
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
      { id: 21, name: 'Barry', role: 'backend-worker', description: 'BE', is_active: true },
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

describe('AgentList reputation (DWB-435)', () => {
  it('shows each agent reputation joined from the project scores', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', reputation: 6, sprint_delta: 6, influence: 20 },
      { agent_id: 21, agent_name: 'Barry', reputation: 35, sprint_delta: 35, influence: 20 },
    ]);
    renderList();

    await waitFor(() => expect(screen.getByText('rep 6')).toBeInTheDocument());
    expect(screen.getByText('rep 35')).toBeInTheDocument();
    expect(getProjectScores).toHaveBeenCalledWith(1);
  });

  it('defaults reputation to 0 when an agent is absent from the scores payload', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', reputation: 6, sprint_delta: 6, influence: 20 },
    ]);
    renderList();

    await waitFor(() => expect(screen.getByText('rep 6')).toBeInTheDocument());
    // Barry has no score row -> defaults to 0
    expect(screen.getByText('rep 0')).toBeInTheDocument();
  });

  it('renders 0 for every agent when the scores fetch fails', async () => {
    getProjectScores.mockRejectedValue(new Error('boom'));
    renderList();

    await waitFor(() => expect(screen.getAllByText('rep 0')).toHaveLength(2));
  });
});
