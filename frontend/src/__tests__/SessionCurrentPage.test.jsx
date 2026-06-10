// Path: src/__tests__/SessionCurrentPage.test.jsx
// File: SessionCurrentPage.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionCurrentPage — thin host for SessionPanel at /projects/:id/sessions/current. Verifies breadcrumb, title, SessionPanel renders, and project-not-found state.
// Caller: vitest test runner
// Callees: ../pages/SessionCurrentPage, ../api/sessions (mocked), ../store/useStore (mocked)
// Data In: Mocked sessions API + store selectors
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

let mockProject = { id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu' };
vi.mock('../store/useStore', () => ({
  default: (selector) => selector({ getProject: () => mockProject }),
}));

import SessionCurrentPage from '../pages/SessionCurrentPage';
import { getProjectSessions, getSession } from '../api/sessions';

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/sessions/current" element={<SessionCurrentPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SessionCurrentPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getProjectSessions.mockReset();
    getSession.mockReset();
    mockProject = { id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu' };
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders breadcrumb, title, and the live SessionPanel for the current session', async () => {
    getProjectSessions.mockResolvedValue([
      { id: 42, opened_at: '2026-06-10T11:55:35', closed_at: null, status: 'open', total_tokens: 0, total_time_seconds: 0, open_method: 'regex' },
    ]);
    getSession.mockResolvedValue({
      id: 42,
      project_id: 1,
      opened_at: '2026-06-10T11:55:35',
      closed_at: null,
      open_method: 'regex',
      status: 'open',
      live: true,
      total_tokens: 1000,
      total_time_seconds: 60,
      by_role: [],
      by_ticket: [],
      tl_overhead_tokens: 0,
      pm_overhead_tokens: 0,
    });

    await act(async () => {
      renderAt('/projects/1/sessions/current');
    });

    await waitFor(() => {
      expect(screen.getByTestId('session-current-page')).toBeInTheDocument();
    });
    expect(screen.getByText(/Current Session:/i)).toBeInTheDocument();

    // Breadcrumb has project + sessions links.
    const links = screen.getAllByRole('link');
    expect(links.some((a) => a.getAttribute('href') === '/projects/1')).toBe(true);
    expect(links.some((a) => a.getAttribute('href') === '/projects/1/sessions')).toBe(true);

    // SessionPanel mounted.
    await waitFor(() => {
      expect(screen.getByText(/SESSION #42/)).toBeInTheDocument();
    });
  });

  it('renders not-found state when project missing', async () => {
    mockProject = null;
    getProjectSessions.mockResolvedValue([]);
    await act(async () => {
      renderAt('/projects/999/sessions/current');
    });
    expect(screen.getByText(/Project not found/i)).toBeInTheDocument();
  });
});
