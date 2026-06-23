// Path: src/__tests__/ProjectAgentsScore.test.jsx
// File: ProjectAgentsScore.test.jsx
// Created: 2026-06-23
// Purpose: Tests for the Roster tab reputation Score column on ProjectAgentsPage (DWB-435). Covers joining reputation from getProjectScores by agent_id and defaulting to 0 when an agent is absent from the scores payload.
// Caller: vitest test runner
// Callees: ../pages/ProjectAgentsPage, ../store/useStore (mocked), ../api/projects (mocked), ../api/scores (mocked), child components (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store state + mocked api modules
// Data Out: Test assertions
// Last Modified: 2026-06-23

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/projects', () => ({
  deployPlaybooks: vi.fn(),
}));

vi.mock('../api/scores', () => ({
  getProjectScores: vi.fn(),
}));

vi.mock('../components/project/PlaybookInspector', () => ({ default: () => null }));
vi.mock('../components/project/Scoreboard', () => ({ default: () => null }));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import ProjectAgentsPage from '../pages/ProjectAgentsPage';
import { getProjectScores } from '../api/scores';

function seed() {
  const project = { id: 1, prefix: 'DWB', repo_path: null };
  const agents = [
    { id: 19, name: 'Freddie', role: 'frontend-worker', description: 'FE', is_active: true },
    { id: 21, name: 'Barry', role: 'backend-worker', description: 'BE', is_active: true },
  ];
  mockState = {
    getProject: () => project,
    getAgentsByProject: () => agents,
  };
}

beforeEach(() => {
  getProjectScores.mockReset();
  seed();
});

afterEach(() => {
  cleanup();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/1/agents']}>
      <Routes>
        <Route path="/projects/:id/agents" element={<ProjectAgentsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ProjectAgentsPage Roster Score column (DWB-435)', () => {
  it('renders a Score cell per agent joined from project scores, 0 when absent', async () => {
    getProjectScores.mockResolvedValue([
      { agent_id: 19, agent_name: 'Freddie', reputation: 6 },
      // Barry absent -> 0
    ]);
    renderPage();

    expect(await screen.findByText('Score')).toBeInTheDocument();

    const freddieRow = screen.getByText('Freddie').closest('tr');
    await waitFor(() => expect(within(freddieRow).getByText('6')).toBeInTheDocument());

    const barryRow = screen.getByText('Barry').closest('tr');
    expect(within(barryRow).getByText('0')).toBeInTheDocument();
  });
});
