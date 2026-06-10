// Path: src/components/project/__tests__/SessionsTable.test.jsx
// File: SessionsTable.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionsTable — header rendering, empty state, default-all behavior (no slice when limit undefined), optional row limit, DWB-346-pending null-guarded aggregate fields, links pointing at session detail route
// Caller: vitest test runner
// Callees: ../SessionsTable, ../../../api/sessions (mocked)
// Data In: Mocked getProjectSessions
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

import SessionsTable from '../SessionsTable';
import { getProjectSessions } from '../../../api/sessions';

function row(overrides = {}) {
  return {
    id: 1,
    opened_at: '2026-06-10T11:55:35',
    closed_at: '2026-06-10T12:30:00',
    total_tokens: 1500000,
    total_time_seconds: 2065,
    status: 'closed',
    open_method: 'regex',
    close_method: 'idle_timeout',
    ...overrides,
  };
}

function wrap(ui) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}

describe('SessionsTable', () => {
  beforeEach(() => {
    getProjectSessions.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders empty state when no sessions exist', async () => {
    getProjectSessions.mockResolvedValue([]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getByText(/No prior sessions yet\./i)).toBeInTheDocument();
    });
  });

  it('header has the exact 8-column set (no Agents / Open / Close columns)', async () => {
    getProjectSessions.mockResolvedValue([row()]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getByText('Tix Made')).toBeInTheDocument();
    });
    for (const label of ['#', 'Start', 'End', 'Duration', 'Tokens', 'Tix Made', 'Tix Done', 'Summary']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // Dropped columns must NOT appear as headers.
    expect(screen.queryByText('Agents')).not.toBeInTheDocument();
    expect(screen.queryByText('Open')).not.toBeInTheDocument();
    expect(screen.queryByText('Close')).not.toBeInTheDocument();
    // Old labels also gone.
    expect(screen.queryByText('Made')).not.toBeInTheDocument();
    expect(screen.queryByText('Done')).not.toBeInTheDocument();
    expect(screen.queryByText('What')).not.toBeInTheDocument();
  });

  it('does not render the open_method / close_method values in rows', async () => {
    getProjectSessions.mockResolvedValue([row({ id: 50, open_method: 'regex', close_method: 'idle_timeout' })]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getByText('#50')).toBeInTheDocument();
    });
    // With the Open/Close columns removed, the enum strings must not appear in the DOM.
    expect(screen.queryByText('regex')).not.toBeInTheDocument();
    expect(screen.queryByText('idle_timeout')).not.toBeInTheDocument();
  });

  it('renders up to limit rows, sorted by opened_at desc', async () => {
    getProjectSessions.mockResolvedValue([
      row({ id: 1, opened_at: '2026-06-08T10:00:00' }),
      row({ id: 2, opened_at: '2026-06-09T10:00:00' }),
      row({ id: 3, opened_at: '2026-06-10T10:00:00' }),
      row({ id: 4, opened_at: '2026-06-07T10:00:00' }),
      row({ id: 5, opened_at: '2026-06-06T10:00:00' }),
      row({ id: 6, opened_at: '2026-06-05T10:00:00' }),
    ]);
    render(wrap(<SessionsTable projectId={1} limit={5} />));
    await waitFor(() => {
      expect(screen.getAllByTestId('recent-session-row')).toHaveLength(5);
    });
    const rows = screen.getAllByTestId('recent-session-row');
    // First (top) row should be the most-recent session (id=3).
    expect(rows[0]).toHaveTextContent('#3');
    // Last visible row should be the 5th most-recent (id=5), not id=6.
    expect(rows[4]).toHaveTextContent('#5');
    expect(screen.queryByText('#6')).not.toBeInTheDocument();
  });

  it('null-guards DWB-346 aggregate fields with dashes while headline is missing', async () => {
    getProjectSessions.mockResolvedValue([row({ id: 7, headline: null, ticket_summary: null })]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getByText('#7')).toBeInTheDocument();
    });
    const r = screen.getByTestId('recent-session-row');
    // Made, Done, Agents, What all dash when their fields are absent.
    expect(r.textContent).toMatch(/-/);
  });

  it('uses headline when present, falls back to ticket_summary, then dash', async () => {
    getProjectSessions.mockResolvedValue([
      row({ id: 11, headline: 'Layer-1 regex fix', ticket_summary: 'should-not-show' }),
      row({ id: 12, headline: null, ticket_summary: 'DWB-339 SessionPanel' }),
      row({ id: 13, headline: null, ticket_summary: null }),
    ]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getAllByTestId('recent-session-row')).toHaveLength(3);
    });
    expect(screen.getByText('Layer-1 regex fix')).toBeInTheDocument();
    expect(screen.getByText('DWB-339 SessionPanel')).toBeInTheDocument();
    expect(screen.queryByText('should-not-show')).not.toBeInTheDocument();
  });

  it('with no limit prop, renders every row returned by the API', async () => {
    getProjectSessions.mockResolvedValue([
      row({ id: 1, opened_at: '2026-06-08T10:00:00' }),
      row({ id: 2, opened_at: '2026-06-09T10:00:00' }),
      row({ id: 3, opened_at: '2026-06-10T10:00:00' }),
      row({ id: 4, opened_at: '2026-06-07T10:00:00' }),
      row({ id: 5, opened_at: '2026-06-06T10:00:00' }),
      row({ id: 6, opened_at: '2026-06-05T10:00:00' }),
    ]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getAllByTestId('recent-session-row')).toHaveLength(6);
    });
    expect(screen.getByText('#6')).toBeInTheDocument();
  });

  it('Duration ticks live for open rows (closed_at == null) and stays frozen for closed rows', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    // Fix wall clock to a known instant so (now - opened_at) is predictable.
    vi.setSystemTime(new Date('2026-06-10T12:00:00Z'));

    getProjectSessions.mockResolvedValue([
      // OPEN session: opened 30s ago, total_time_seconds reported as 0 by the API (stale).
      row({ id: 100, opened_at: '2026-06-10T11:59:30Z', closed_at: null, status: 'open', total_time_seconds: 0 }),
      // CLOSED session: total_time_seconds is the frozen number we must display verbatim.
      row({ id: 101, opened_at: '2026-06-10T10:00:00Z', closed_at: '2026-06-10T10:30:00Z', status: 'closed', total_time_seconds: 1800 }),
    ]);

    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getAllByTestId('recent-session-row')).toHaveLength(2);
    });

    const openRowEl = screen.getByText('#100').closest('a');
    const closedRowEl = screen.getByText('#101').closest('a');

    // Open row: live elapsed = 30s, not the stale "0s" from the API.
    expect(openRowEl.textContent).toMatch(/30s/);
    expect(openRowEl.textContent).not.toMatch(/(^|[^\d])0s($|[^\d])/);
    // Closed row: frozen 30 min.
    expect(closedRowEl.textContent).toMatch(/30m/);

    // Advance 10s — advanceTimersByTime moves the fake clock AND fires the
    // 10s interval, so the row's `now` reads the new wall time on re-render.
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    // Open row: now 40s. Closed row: still 30 min (frozen).
    expect(openRowEl.textContent).toMatch(/40s/);
    expect(closedRowEl.textContent).toMatch(/30m/);
  });

  it('rows are anchor links to /projects/:pid/sessions/:sid', async () => {
    getProjectSessions.mockResolvedValue([row({ id: 99 })]);
    render(wrap(<SessionsTable projectId={1} />));
    await waitFor(() => {
      expect(screen.getByText('#99')).toBeInTheDocument();
    });
    const r = screen.getByTestId('recent-session-row');
    expect(r.tagName).toBe('A');
    expect(r.getAttribute('href')).toBe('/projects/1/sessions/99');
  });
});
