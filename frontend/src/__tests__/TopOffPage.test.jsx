// Path: src/__tests__/TopOffPage.test.jsx
// File: TopOffPage.test.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: Tests for the top-off landing page - the link DWB-590 has been
//          emitting since it shipped, previously dead. Covers the
//          enabled/interval status, live-session prompt_count rows, the
//          "until next check" arithmetic (including the top-off-disabled
//          and interval-just-hit cases), and the no-active-sessions state.
// Caller: vitest test runner
// Callees: ../pages/TopOffPage, ../store/useStore (mocked), ../api/hooks (mocked)
// Data In: Mocked store project + mocked getHookSessions responses
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-613)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/hooks', () => ({
  getHookSessions: vi.fn(),
}));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import TopOffPage from '../pages/TopOffPage';
import { getHookSessions } from '../api/hooks';

function seed(overrides = {}) {
  mockState = {
    projects: [{ id: 5, prefix: 'DWB', name: 'D Waantu B Guantu', topoff_enabled: true, topoff_interval: 10, ...overrides }],
  };
}

beforeEach(() => {
  getHookSessions.mockReset();
  seed();
});

afterEach(() => {
  cleanup();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/5/topoff']}>
      <Routes>
        <Route path="/projects/:id/topoff" element={<TopOffPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('TopOffPage (DWB-613)', () => {
  it('renders the enabled/interval status', async () => {
    getHookSessions.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText('yes')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
  });

  it('shows each live session prompt_count and prompts remaining until the next check', async () => {
    getHookSessions.mockResolvedValue([
      { id: 1, agent_id: 3, agent_name: 'Freddie', prompt_count: 7 },
      { id: 2, agent_id: 4, agent_name: 'Sylvie', prompt_count: 10 },
    ]);
    renderPage();

    const table = await screen.findByTestId('topoff-sessions');
    const freddieRow = within(table).getByText('Freddie').closest('tr');
    expect(within(freddieRow).getByText('7')).toBeInTheDocument();
    expect(within(freddieRow).getByText('3')).toBeInTheDocument(); // 10 - (7 % 10)

    const sylvieRow = within(table).getByText('Sylvie').closest('tr');
    expect(within(sylvieRow).getByText('due now')).toBeInTheDocument(); // 10 % 10 == 0
  });

  it('says top-off is off instead of computing a remaining count when disabled', async () => {
    seed({ topoff_enabled: false });
    getHookSessions.mockResolvedValue([
      { id: 1, agent_id: 3, agent_name: 'Freddie', prompt_count: 4 },
    ]);
    renderPage();

    expect(await screen.findByText('top-off is off')).toBeInTheDocument();
  });

  it('shows a clean empty state with no active sessions', async () => {
    getHookSessions.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByTestId('topoff-empty')).toHaveTextContent('no active sessions');
  });

  it('requests only this project\'s active sessions', async () => {
    getHookSessions.mockResolvedValue([]);
    renderPage();

    await screen.findByTestId('topoff-empty');
    expect(getHookSessions).toHaveBeenCalledWith({ project_id: 5, status: 'active' });
  });
});
