// Path: src/components/project/__tests__/SessionPanel.test.jsx
// File: SessionPanel.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionPanel — empty state when project has no sessions, open session rendering with live polling tick, closed session frozen rendering, and polling cessation after close
// Caller: vitest test runner
// Callees: ../SessionPanel, ../../../api/sessions (mocked)
// Data In: Mocked getProjectSessions / getSession responses
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';

// Mock the sessions API before importing the component.
vi.mock('../../../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

import SessionPanel from '../SessionPanel';
import { getProjectSessions, getSession } from '../../../api/sessions';

function openSessionDetail(overrides = {}) {
  return {
    id: 42,
    project_id: 1,
    opened_at: '2026-06-10T11:55:35',
    closed_at: null,
    open_phrase: 'you are archie, read the playbook',
    close_phrase: null,
    open_method: 'regex',
    close_method: null,
    close_reason: null,
    status: 'open',
    live: true,
    total_tokens: 1234567,
    total_time_seconds: 827,
    by_role: [
      { agent_id: 13, agent_name: 'Archie_DWB', role: 'team-lead', tokens: 800000, time_seconds: 600 },
      { agent_id: 19, agent_name: 'Freddie', role: 'frontend-worker', tokens: 200000, time_seconds: 120 },
    ],
    by_ticket: [
      { ticket_id: 819, ticket_key: 'DWB-339', title: 'SessionPanel build', tokens: 1000000, time_seconds: 700 },
    ],
    tl_overhead_tokens: 800000,
    pm_overhead_tokens: 0,
    ...overrides,
  };
}

function closedSessionDetail(overrides = {}) {
  return {
    id: 41,
    project_id: 1,
    opened_at: '2026-06-09T17:20:15',
    closed_at: '2026-06-09T19:32:33',
    open_phrase: 'you are archie, read the playbook',
    close_phrase: 'shut it down for the night',
    open_method: 'ai_confident',
    close_method: 'idle_timeout',
    close_reason: 'idle',
    status: 'closed',
    live: false,
    total_tokens: 4500000,
    total_time_seconds: 7938,
    by_role: [],
    by_ticket: [],
    tl_overhead_tokens: 0,
    pm_overhead_tokens: 0,
    ...overrides,
  };
}

describe('SessionPanel', () => {
  beforeEach(() => {
    // Only fake the interval timers used by polling, not setTimeout — so
    // @testing-library/react's waitFor (which leans on setTimeout) keeps working.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getProjectSessions.mockReset();
    getSession.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders empty state when project has no sessions', async () => {
    getProjectSessions.mockResolvedValue([]);
    getSession.mockResolvedValue(null);

    await act(async () => {
      render(<SessionPanel projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText(/No active DWB session\./i)).toBeInTheDocument();
    });
    expect(screen.getByText(/you are archie, read the playbook/i)).toBeInTheDocument();
    // No polling timer should be scheduled when no session exists.
    expect(vi.getTimerCount()).toBe(0);
  });

  it('renders an open session with header, totals, and by_role/by_ticket tables, and polls', async () => {
    getProjectSessions.mockResolvedValue([
      { id: 42, opened_at: '2026-06-10T11:55:35', closed_at: null, status: 'open', total_tokens: 0, total_time_seconds: 0 },
    ]);
    getSession.mockResolvedValueOnce(openSessionDetail());

    await act(async () => {
      render(<SessionPanel projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText(/SESSION #42/)).toBeInTheDocument();
    });

    expect(screen.getByText(/open since/i)).toBeInTheDocument();
    expect(screen.getByText(/open: regex/i)).toBeInTheDocument();
    expect(screen.getByText('Archie_DWB')).toBeInTheDocument();
    expect(screen.getByText('Freddie')).toBeInTheDocument();
    expect(screen.getByText('DWB-339')).toBeInTheDocument();
    expect(screen.getByText('SessionPanel build')).toBeInTheDocument();
    expect(screen.getByText(/TL overhead/i)).toBeInTheDocument();
    // Ad Hoc row renders alongside TL/PM whenever the overhead block is visible.
    // Null-guarded to 0 pre-DWB-353; fixture has no ad_hoc_overhead_tokens field.
    expect(screen.getByTestId('session-panel-ad-hoc-overhead')).toBeInTheDocument();
    expect(screen.getByTestId('session-panel-ad-hoc-overhead').textContent).toMatch(/Ad Hoc/);

    // After initial render, polling timer should be active.
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    // Advance time to trigger one poll cycle; expect getSession called again.
    const callsBeforeTick = getSession.mock.calls.length;
    getSession.mockResolvedValueOnce(openSessionDetail({ total_tokens: 2000000 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(getSession.mock.calls.length).toBeGreaterThan(callsBeforeTick);
  });

  it('renders a closed session frozen and stops polling', async () => {
    getProjectSessions.mockResolvedValue([
      { id: 41, opened_at: '2026-06-09T17:20:15', closed_at: '2026-06-09T19:32:33', status: 'closed', total_tokens: 4500000, total_time_seconds: 7938 },
    ]);
    getSession.mockResolvedValueOnce(closedSessionDetail());

    await act(async () => {
      render(<SessionPanel projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText(/SESSION #41/)).toBeInTheDocument();
    });

    expect(screen.getByText(/closed at/i)).toBeInTheDocument();
    expect(screen.getByText(/close: idle_timeout/i)).toBeInTheDocument();
    // Privacy directive: captured close_phrase text must NOT appear in DOM.
    expect(screen.queryByText(/shut it down for the night/i)).not.toBeInTheDocument();

    // No polling timer should be active on a closed session.
    expect(vi.getTimerCount()).toBe(0);

    // Advance time; getSession should NOT be called again.
    const callsAfterMount = getSession.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(getSession.mock.calls.length).toBe(callsAfterMount);
  });

  it('stops polling when an open session transitions to closed mid-poll', async () => {
    getProjectSessions
      .mockResolvedValueOnce([
        { id: 50, opened_at: '2026-06-10T11:55:35', closed_at: null, status: 'open', total_tokens: 0, total_time_seconds: 0 },
      ])
      .mockResolvedValueOnce([
        { id: 50, opened_at: '2026-06-10T11:55:35', closed_at: '2026-06-10T12:30:00', status: 'closed', total_tokens: 5000, total_time_seconds: 2000 },
      ]);
    getSession
      .mockResolvedValueOnce(openSessionDetail({ id: 50 }))
      .mockResolvedValueOnce(closedSessionDetail({ id: 50, total_tokens: 5000, total_time_seconds: 2000 }));

    await act(async () => {
      render(<SessionPanel projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText(/open since/i)).toBeInTheDocument();
    });
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    // First poll: session has now closed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    await waitFor(() => {
      expect(screen.getByText(/closed at/i)).toBeInTheDocument();
    });

    // Polling should have been cleared once the freeze condition was detected.
    expect(vi.getTimerCount()).toBe(0);
  });
});
