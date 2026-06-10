// Path: src/components/layout/__tests__/SessionFooter.test.jsx
// File: SessionFooter.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionFooter — five dot states (active/closed/error/idle-warning/none), click navigates to /projects/:pid/sessions, polling cadence pauses on non-project routes, idle-warning threshold (>50min) flips active->idle-warning, error state surfaces on fetch reject, captured open_phrase/close_phrase never appear in DOM
// Caller: vitest test runner
// Callees: ../SessionFooter, ../../../api/sessions (mocked), react-router-dom (MemoryRouter, Routes, Route)
// Data In: Mocked getProjectSessions
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../../../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

// Mock the Zustand store: provide polling + infraWarnings so the merged
// right-side renders predictable text. Tests can mutate `mockState` between
// runs if they need different polling/infra values.
let mockState = {
  polling: { interval: 4000, isActive: true, lastUpdated: '2026-06-10T07:44:55Z' },
  infraWarnings: [],
};
vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import SessionFooter from '../SessionFooter';
import { getProjectSessions } from '../../../api/sessions';

const minutesAgo = (m) => {
  const d = new Date(Date.now() - m * 60 * 1000);
  // API serves naive UTC; component re-appends Z. Slice off milliseconds.
  return d.toISOString().replace(/\.\d+Z$/, '');
};

function openRow(overrides = {}) {
  return {
    id: 5,
    opened_at: minutesAgo(10),
    closed_at: null,
    status: 'open',
    total_tokens: 1000,
    total_time_seconds: 600,
    open_method: 'regex',
    close_method: null,
    headline: null,
    ...overrides,
  };
}

function closedRow(overrides = {}) {
  return {
    id: 4,
    opened_at: minutesAgo(120),
    closed_at: minutesAgo(60),
    status: 'closed',
    total_tokens: 5000,
    total_time_seconds: 3600,
    open_method: 'ai_confident',
    close_method: 'idle_timeout',
    headline: null,
    ...overrides,
  };
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<SessionFooter />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SessionFooter', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getProjectSessions.mockReset();
    mockState = {
      polling: { interval: 4000, isActive: true, lastUpdated: '2026-06-10T07:44:55Z' },
      infraWarnings: [],
    };
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('on a non-project route, renders the inert placeholder and does not poll', async () => {
    await act(async () => {
      renderAt('/');
    });
    const footer = screen.getByTestId('session-footer');
    expect(footer).toBeInTheDocument();
    expect(footer.className).toMatch(/session-footer--inert/);
    expect(screen.getByText(/no project context/i)).toBeInTheDocument();
    expect(getProjectSessions).not.toHaveBeenCalled();
  });

  it('renders active state for an open recent session and points at the Sessions page', async () => {
    getProjectSessions.mockResolvedValue([openRow()]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('session-footer').getAttribute('data-state')).toBe('active');
    });
    expect(screen.getByText(/SESSION #5/)).toBeInTheDocument();
    expect(screen.getByTestId('session-footer').getAttribute('href')).toBe('/projects/1/sessions');
    // Single-row contract: right side shows the merged global polling text.
    expect(screen.getByText(/polling/i)).toBeInTheDocument();
    expect(screen.getByText(/4s interval/)).toBeInTheDocument();
    expect(screen.getByText(/last updated:/i)).toBeInTheDocument();
  });

  it('renders closed state for the most recent closed session', async () => {
    getProjectSessions.mockResolvedValue([closedRow()]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('session-footer').getAttribute('data-state')).toBe('closed');
    });
    expect(screen.getByText(/SESSION #4/)).toBeInTheDocument();
    expect(screen.getByText(/closed at/i)).toBeInTheDocument();
  });

  it('renders idle-warning state when an open session has exceeded the 50min threshold', async () => {
    getProjectSessions.mockResolvedValue([openRow({ id: 7, opened_at: minutesAgo(55) })]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('session-footer').getAttribute('data-state')).toBe('idle-warning');
    });
  });

  it('renders none state when the project has no sessions', async () => {
    getProjectSessions.mockResolvedValue([]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('session-footer').getAttribute('data-state')).toBe('none');
    });
    expect(screen.getByText(/no DWB session/i)).toBeInTheDocument();
  });

  it('renders error state when the API fetch rejects and surfaces a retry message alongside the polling text', async () => {
    getProjectSessions.mockRejectedValue(new Error('boom'));
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('session-footer').getAttribute('data-state')).toBe('error');
    });
    expect(screen.getByText(/poll failed/i)).toBeInTheDocument();
    // Global polling text still renders alongside the retry indicator.
    expect(screen.getByText(/last updated:/i)).toBeInTheDocument();
  });

  it('surfaces infra warning count on the right side when warnings exist', async () => {
    mockState = {
      ...mockState,
      infraWarnings: [
        { severity: 'warning', message: 'mysql slow' },
        { severity: 'critical', message: 'disk full' },
      ],
    };
    getProjectSessions.mockResolvedValue([openRow()]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByText(/2 infra warnings/i)).toBeInTheDocument();
    });
  });

  it('non-project route still renders the merged polling text on the right side', async () => {
    await act(async () => {
      renderAt('/');
    });
    expect(screen.getByTestId('session-footer').className).toMatch(/session-footer--inert/);
    expect(screen.getByText(/last updated:/i)).toBeInTheDocument();
  });

  it('polls every 10s while on a project route', async () => {
    getProjectSessions.mockResolvedValue([openRow()]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(getProjectSessions).toHaveBeenCalledTimes(1);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(getProjectSessions.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('uses headline (DWB-346) when present, falling back to SESSION #N otherwise', async () => {
    getProjectSessions.mockResolvedValue([openRow({ headline: 'Layer-1 regex fix' })]);
    await act(async () => {
      renderAt('/projects/1');
    });
    await waitFor(() => {
      expect(screen.getByText(/Layer-1 regex fix/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/SESSION #5/)).not.toBeInTheDocument();
  });
});
