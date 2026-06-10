// Path: src/__tests__/SessionDetailPage.test.jsx
// File: SessionDetailPage.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionDetailPage — route resolves and fetches by :sid, full payload renders (header, methods, phrases, by_role, by_ticket, overhead), back link points to the sessions list, 404 path shows a session-not-found view with back navigation, polling cease on closed sessions
// Caller: vitest test runner
// Callees: ../pages/SessionDetailPage, ../api/sessions (mocked), ../api/client (ApiError), ../store/useStore (mocked)
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

import SessionDetailPage from '../pages/SessionDetailPage';
import { getSession } from '../api/sessions';
import { ApiError } from '../api/client';

function closedDetail(overrides = {}) {
  return {
    id: 4,
    project_id: 1,
    opened_at: '2026-06-09T17:20:15',
    closed_at: '2026-06-09T19:32:33',
    open_phrase: 'you are archie, read the playbook',
    close_phrase: 'shut it down for the night',
    open_method: 'ai_confident',
    close_method: 'idle_timeout',
    close_reason: 'idle',
    headline: 'Layer-1 regex fix',
    status: 'closed',
    live: false,
    total_tokens: 5567456,
    total_time_seconds: 7938,
    by_role: [
      { agent_id: 13, agent_name: 'Archie_DWB', role: 'team-lead', tokens: 3681701, time_seconds: 8094 },
      { agent_id: 21, agent_name: 'Barry_DWB', role: 'backend-worker', tokens: 1343068, time_seconds: 172 },
    ],
    by_ticket: [
      { ticket_id: 832, ticket_key: 'DWB-343', title: 'Layer-1 retry', tokens: 1343068, time_seconds: 159 },
    ],
    tl_overhead_tokens: 3681701,
    pm_overhead_tokens: 344647,
    ...overrides,
  };
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/sessions/:sid" element={<SessionDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SessionDetailPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getSession.mockReset();
    mockProject = { id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu' };
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders the full payload for a closed session with back link, methods, phrases, by_role, by_ticket, overhead', async () => {
    getSession.mockResolvedValue(closedDetail());

    await act(async () => {
      renderAt('/projects/1/sessions/4');
    });

    await waitFor(() => {
      expect(screen.getByText(/DWB Session #4/)).toBeInTheDocument();
    });

    // Breadcrumb: project + sessions back link.
    expect(screen.getByText('DWB')).toBeInTheDocument();
    const backLinks = screen.getAllByRole('link', { name: /sessions/ });
    expect(backLinks.some((a) => a.getAttribute('href') === '/projects/1/sessions')).toBe(true);

    // Methods + reason.
    expect(screen.getByText(/open via ai_confident/i)).toBeInTheDocument();
    expect(screen.getByText(/close via idle_timeout/i)).toBeInTheDocument();
    expect(screen.getByText(/reason: idle/i)).toBeInTheDocument();

    // Headline.
    expect(screen.getByTestId('session-detail-headline')).toHaveTextContent('Layer-1 regex fix');

    // Privacy directive: captured open_phrase / close_phrase text must NOT appear in DOM.
    expect(screen.queryByText(/you are archie, read the playbook/)).not.toBeInTheDocument();
    expect(screen.queryByText(/shut it down for the night/)).not.toBeInTheDocument();

    // by_role rows.
    expect(screen.getByText('Archie_DWB')).toBeInTheDocument();
    expect(screen.getByText('Barry_DWB')).toBeInTheDocument();

    // by_ticket rows include link to ticket detail.
    const ticketLink = screen.getByRole('link', { name: 'DWB-343' });
    expect(ticketLink.getAttribute('href')).toBe('/projects/1/tickets/832');

    // Overhead row: TL + PM + Ad Hoc, all three always rendered on the detail
    // page (drill-down view). Ad Hoc null-guards to 0 pre-DWB-353.
    expect(screen.getByText(/TL overhead/)).toBeInTheDocument();
    expect(screen.getByText(/PM overhead/)).toBeInTheDocument();
    expect(screen.getByTestId('session-detail-ad-hoc-overhead')).toBeInTheDocument();
    expect(screen.getByTestId('session-detail-ad-hoc-overhead').textContent).toMatch(/Ad Hoc/);

    // Closed session: no polling timer scheduled.
    expect(vi.getTimerCount()).toBe(0);
  });

  it('renders a not-found view with back link on 404', async () => {
    getSession.mockRejectedValue(new ApiError('Not found', 404, null));

    await act(async () => {
      renderAt('/projects/1/sessions/99999');
    });

    await waitFor(() => {
      expect(screen.getByTestId('session-not-found')).toBeInTheDocument();
    });
    expect(screen.getByText(/Session #99999 not found\./)).toBeInTheDocument();

    const back = screen.getByRole('link', { name: /back to sessions/i });
    expect(back.getAttribute('href')).toBe('/projects/1/sessions');
  });

  it('polls an open session and stops when it closes', async () => {
    getSession
      .mockResolvedValueOnce(closedDetail({ id: 5, closed_at: null, status: 'open', live: true, close_phrase: null, close_method: null, close_reason: null }))
      .mockResolvedValueOnce(closedDetail({ id: 5 })); // next tick: closed

    await act(async () => {
      renderAt('/projects/1/sessions/5');
    });

    await waitFor(() => {
      expect(screen.getByText(/DWB Session #5/)).toBeInTheDocument();
    });
    expect(screen.getByText('OPEN')).toBeInTheDocument();
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    await waitFor(() => {
      expect(screen.getByText('CLOSED')).toBeInTheDocument();
    });
    expect(vi.getTimerCount()).toBe(0);
  });
});
