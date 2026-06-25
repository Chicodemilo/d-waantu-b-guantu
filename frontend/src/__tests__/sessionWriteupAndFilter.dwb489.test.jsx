// Path: src/__tests__/sessionWriteupAndFilter.dwb489.test.jsx
// File: sessionWriteupAndFilter.dwb489.test.jsx
// Created: 2026-06-25
// Purpose: Frontend tests for DWB-489 - the session write-up + list fuzzy filter,
//          at the level Freddie's component tests do NOT reach. Deliberately
//          complementary, not duplicative: SessionSummary's own render (lead,
//          sorted keyword tags, collapsible sections + bullets, empty state) is
//          already covered by components/project/__tests__/SessionSummary.test.jsx
//          (DWB-486, 7 tests), and the SessionsTable fuzzy match across
//          headline/summary/keywords/ticket-keys is covered by the DWB-487 block
//          in SessionsTable.test.jsx. This file adds the two uncovered seams:
//          (1) SessionDetailPage wiring the real getSession payload's summary +
//          keywords THROUGH to a rendered write-up (and the legacy null-summary
//          empty state) at the PAGE level, and (2) the filter "clearing the query
//          restores the full list" round-trip the existing filter tests skip.
// Caller: vitest test runner
// Callees: ../pages/SessionDetailPage, ../components/project/SessionsTable,
//          ../api/sessions (mocked), ../store/useStore (mocked)
// Data In: mocked getSession + getProjectSessions
// Data Out: test assertions
// Last Modified: 2026-06-25

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

let mockProject = { id: 1, prefix: 'DWB', name: "D'Waantu B'Guantu" };
vi.mock('../store/useStore', () => ({
  default: (selector) => selector({ getProject: () => mockProject }),
}));

import SessionDetailPage from '../pages/SessionDetailPage';
import SessionsTable from '../components/project/SessionsTable';
import { getSession, getProjectSessions } from '../api/sessions';

// A closed-session detail payload carrying the DWB-483 summary JSON + DWB-481
// weighted keywords, as the read API (DWB-493) now returns them.
function detailWithWriteup(overrides = {}) {
  return {
    id: 7,
    project_id: 1,
    opened_at: '2026-06-25T10:00:00',
    closed_at: '2026-06-25T11:30:00',
    open_method: 'regex',
    close_method: 'idle_timeout',
    close_reason: 'idle',
    headline: 'Session synthesizer close-path wiring',
    status: 'closed',
    live: false,
    total_tokens: 1234567,
    total_time_seconds: 5400,
    by_role: [],
    by_ticket: [],
    summary: {
      lead: 'Wired the synthesizer into every session close path.',
      sections: [
        { title: 'Tickets', bullets: ['DWB-488 backend wiring landed', 'DWB-489 frontend tests in flight'] },
      ],
    },
    keywords: [
      { keyword: 'synthesizer', weight: 40 },
      { keyword: 'idle_timeout', weight: 12 },
    ],
    ...overrides,
  };
}

function renderDetailAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/sessions/:sid" element={<SessionDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function tableRow(overrides = {}) {
  return {
    id: 1,
    opened_at: '2026-06-25T11:00:00',
    closed_at: '2026-06-25T12:00:00',
    total_tokens: 1000000,
    total_time_seconds: 2000,
    status: 'closed',
    open_method: 'regex',
    close_method: 'idle_timeout',
    ...overrides,
  };
}

function wrap(ui) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}

describe('SessionDetailPage write-up integration (DWB-489)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getSession.mockReset();
    mockProject = { id: 1, prefix: 'DWB', name: "D'Waantu B'Guantu" };
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders the synthesized write-up (lead, keyword tags, section bullets) from the getSession payload', async () => {
    getSession.mockResolvedValue(detailWithWriteup());

    await act(async () => {
      renderDetailAt('/projects/1/sessions/7');
    });

    await waitFor(() => {
      expect(screen.getByTestId('session-summary')).toBeInTheDocument();
    });

    // Lead line wired through from detail.summary.lead.
    expect(
      screen.getByText('Wired the synthesizer into every session close path.')
    ).toBeInTheDocument();

    // Weighted keyword tags wired through from detail.keywords.
    const tags = screen.getByTestId('session-summary-keywords');
    expect(tags).toHaveTextContent('synthesizer');
    expect(tags).toHaveTextContent('idle_timeout');

    // Section bullets render (sections default open on the detail page).
    expect(screen.getByText('DWB-488 backend wiring landed')).toBeInTheDocument();
    expect(screen.getByText('DWB-489 frontend tests in flight')).toBeInTheDocument();
  });

  it('shows the graceful empty state for a legacy session with no summary or keywords', async () => {
    getSession.mockResolvedValue(
      detailWithWriteup({ summary: null, keywords: [] })
    );

    await act(async () => {
      renderDetailAt('/projects/1/sessions/7');
    });

    await waitFor(() => {
      expect(screen.getByTestId('session-summary-empty')).toBeInTheDocument();
    });
    expect(
      screen.getByText('No write-up recorded for this session.')
    ).toBeInTheDocument();
    expect(screen.queryByTestId('session-summary-keywords')).toBeNull();
  });
});

describe('SessionsTable fuzzy filter clear restores (DWB-489)', () => {
  beforeEach(() => {
    getProjectSessions.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('clearing the query after a filter restores the full list', async () => {
    getProjectSessions.mockResolvedValue([
      tableRow({ id: 1, opened_at: '2026-06-25T11:00:00', headline: 'Inter-agent comms capture' }),
      tableRow({ id: 2, opened_at: '2026-06-24T11:00:00', headline: 'Scoring leaderboard work' }),
    ]);
    render(wrap(<SessionsTable projectId={1} searchable />));
    await waitFor(() =>
      expect(screen.getAllByTestId('recent-session-row')).toHaveLength(2)
    );

    const input = screen.getByLabelText('search sessions');

    // Typing filters to the matching row only.
    fireEvent.change(input, { target: { value: 'comms' } });
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.queryByText('#2')).toBeNull();

    // Clearing the query restores every row.
    fireEvent.change(input, { target: { value: '' } });
    expect(screen.getAllByTestId('recent-session-row')).toHaveLength(2);
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();
  });
});
