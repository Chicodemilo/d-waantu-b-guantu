// Path: src/__tests__/SessionsPage.test.jsx
// File: SessionsPage.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionsPage after DWB-349 restructure — page renders breadcrumb + title, the SessionsTable is the primary content (every session, no slice), the live SessionPanel is NOT inlined here (moved to /sessions/current via a header link), the phrase-help footer block is always visible, and not-found state when the project is missing
// Caller: vitest test runner
// Callees: ../pages/SessionsPage, ../api/sessions (mocked), ../store/useStore (mocked)
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

import SessionsPage from '../pages/SessionsPage';
import { getProjectSessions } from '../api/sessions';

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/sessions" element={<SessionsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SessionsPage (post-DWB-349 restructure)', () => {
  beforeEach(() => {
    getProjectSessions.mockReset();
    mockProject = { id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu' };
  });

  afterEach(() => {
    cleanup();
  });

  it('renders title, breadcrumb, current-session link, and a full SessionsTable as primary content', async () => {
    getProjectSessions.mockResolvedValue([
      { id: 42, opened_at: '2026-06-10T11:55:35', closed_at: null, status: 'open', total_tokens: 0, total_time_seconds: 0, open_method: 'regex' },
      { id: 41, opened_at: '2026-06-09T17:20:15', closed_at: '2026-06-09T19:32:33', status: 'closed', total_tokens: 100, total_time_seconds: 7938, open_method: 'ai_confident', close_method: 'idle_timeout' },
    ]);

    await act(async () => {
      renderAt('/projects/1/sessions');
    });

    await waitFor(() => {
      expect(screen.getByTestId('sessions-page')).toBeInTheDocument();
    });
    expect(screen.getByText(/DWB Sessions/i)).toBeInTheDocument();
    expect(screen.getByText('DWB')).toBeInTheDocument(); // breadcrumb crumb

    // Header link to the current-session drill-down.
    const currentLink = screen.getByTestId('current-session-link');
    expect(currentLink.getAttribute('href')).toBe('/projects/1/sessions/current');

    // SessionsTable populated with BOTH rows (no limit slice).
    await waitFor(() => {
      expect(screen.getAllByTestId('recent-session-row')).toHaveLength(2);
    });
    expect(screen.getByText('#42')).toBeInTheDocument();
    expect(screen.getByText('#41')).toBeInTheDocument();

    // SessionPanel is NOT inlined on this page anymore.
    expect(screen.queryByText(/SESSION #42/)).not.toBeInTheDocument();

    // Phrase-help block is always visible AND sits at the top (before the table).
    const help = screen.getByTestId('phrase-help');
    expect(help).toBeInTheDocument();
    expect(help.textContent).toMatch(/Open with:/);
    expect(help.textContent).toMatch(/Close with:/);

    // Examples are joined with " or " (not "/").
    expect(help.textContent).toMatch(/"you are archie, read the playbook" or "open the session"/);
    expect(help.textContent).toMatch(/"shut it down for the night" or "write docs and exit"/);

    // Inline (info) affordance is present (no modal — uses <details>).
    const info = screen.getByTestId('phrase-info');
    expect(info.tagName.toLowerCase()).toBe('details');
    expect(info.textContent).toMatch(/\(info\)/);
    expect(info.textContent).toMatch(/regex layer/);
    expect(info.textContent).toMatch(/backend\/app\/config\/session_phrases\.py/);

    // Top placement: phrase-help appears in DOM order BEFORE the first session row.
    const firstRow = screen.getAllByTestId('recent-session-row')[0];
    expect(help.compareDocumentPosition(firstRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('renders not-found state when project missing', async () => {
    mockProject = null;
    getProjectSessions.mockResolvedValue([]);
    await act(async () => {
      renderAt('/projects/999/sessions');
    });
    expect(screen.getByText(/Project not found/i)).toBeInTheDocument();
  });
});
