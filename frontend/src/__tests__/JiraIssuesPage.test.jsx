// Path: src/__tests__/JiraIssuesPage.test.jsx
// File: JiraIssuesPage.test.jsx
// Created: 2026-06-10
// Purpose: Tests for DWB-342 unified Jira page. Covers: non-Jira project empty state, populated 10-column table render with null-guarded jira_sprint/jira_reporter (pre-DWB-356), debounced fuzzy search call shape, sortable column header toggle (asc<->desc), row click navigates to DWB ticket detail, manual sync button POSTs + refetches + shows last-synced summary, 409 race kicks the page into poll mode
// Caller: vitest test runner
// Callees: ../pages/JiraIssuesPage, ../api/jira (mocked), ../api/client (ApiError), ../store/useStore (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked Jira API responses + store project
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/jira', () => ({
  getProjectJiraTickets: vi.fn(),
  triggerProjectJiraSync: vi.fn(),
  getProjectJiraSyncStatus: vi.fn(),
}));

let mockProject = {
  id: 5,
  prefix: 'FRAUDI',
  name: 'FRAUDI',
  jira_project_key: 'FRAUDI',
};
vi.mock('../store/useStore', () => ({
  default: (selector) => selector({ getProject: () => mockProject }),
}));

import JiraIssuesPage from '../pages/JiraIssuesPage';
import {
  getProjectJiraTickets,
  triggerProjectJiraSync,
  getProjectJiraSyncStatus,
} from '../api/jira';
import { ApiError } from '../api/client';

function row(overrides = {}) {
  return {
    ticket_id: 1001,
    dwb_key: 'FRA-101',
    dwb_sprint: 'FRA Sprint 4',
    dwb_status: 'in_progress',
    jira_key: 'FRA-101',
    jira_sprint: 'Sprint 12',
    jira_status: 'In Progress',
    jira_assignee: 'Alice',
    jira_reporter: 'Bob',
    title: 'Wire up the claims endpoint',
    created_at: '2026-06-05T09:00:00',
    updated_at: '2026-06-09T17:00:00',
    jira_created_at: '2026-06-05T09:00:00',
    jira_updated_at: '2026-06-09T17:00:00',
    last_synced_at: '2026-06-10T08:00:00',
    ...overrides,
  };
}

function listResp(rows, total) {
  return {
    project_id: 5,
    project_prefix: 'FRAUDI',
    total: total ?? rows.length,
    limit: 200,
    offset: 0,
    rows,
  };
}

function renderAt(path = '/projects/5/jira') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/jira" element={<JiraIssuesPage />} />
        <Route path="/projects/:id/tickets/:ticketId" element={<div data-testid="ticket-detail-stub" />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('JiraIssuesPage (DWB-342)', () => {
  beforeEach(() => {
    // Only fake setInterval (sync polling) — leave setTimeout real so the
    // search-input debounce and @testing-library waitFor both work normally.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getProjectJiraTickets.mockReset();
    triggerProjectJiraSync.mockReset();
    getProjectJiraSyncStatus.mockReset();
    mockProject = { id: 5, prefix: 'FRAUDI', name: 'FRAUDI', jira_project_key: 'FRAUDI' };
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders the not-linked empty state when the project has no jira_project_key', async () => {
    mockProject = { id: 1, prefix: 'DWB', name: 'DWB', jira_project_key: null };
    await act(async () => {
      renderAt('/projects/1/jira');
    });
    expect(screen.getByTestId('jira-page')).toBeInTheDocument();
    expect(screen.getByText(/not linked to a Jira project/i)).toBeInTheDocument();
    // No fetch attempted.
    expect(getProjectJiraTickets).not.toHaveBeenCalled();
  });

  it('renders the populated 10-column table and null-guards jira_sprint to a dash when null (pre-DWB-356)', async () => {
    getProjectJiraTickets.mockResolvedValue(
      listResp([
        row(),
        row({ ticket_id: 1002, dwb_key: 'FRA-102', jira_key: 'FRA-102', jira_sprint: null, jira_assignee: null, title: 'Patch the snapshot normalizer' }),
      ])
    );
    getProjectJiraSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, counts: null });

    await act(async () => {
      renderAt();
    });

    await waitFor(() => {
      expect(screen.getByTestId('jira-table')).toBeInTheDocument();
    });

    // All 10 column headers render.
    for (const key of ['dwb_key','dwb_sprint','dwb_status','jira_key','jira_sprint','jira_status','jira_assignee','created_at','updated_at','title']) {
      expect(screen.getByTestId(`jira-col-${key}`)).toBeInTheDocument();
    }

    expect(screen.getAllByTestId('jira-row')).toHaveLength(2);
    expect(screen.getByText('Wire up the claims endpoint')).toBeInTheDocument();

    // Null-guard: the second row has jira_sprint=null and jira_assignee=null.
    // The corresponding cells should render "-" rather than crashing.
    const second = screen.getAllByTestId('jira-row')[1];
    expect(second.textContent).toMatch(/-/);
    expect(second.textContent).toContain('FRA-102');
  });

  it('debounces the search input and re-issues the fetch with q=', async () => {
    getProjectJiraTickets.mockResolvedValue(listResp([row()]));
    getProjectJiraSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, counts: null });

    await act(async () => {
      renderAt();
    });
    await waitFor(() => {
      expect(getProjectJiraTickets).toHaveBeenCalledTimes(1);
    });

    const input = screen.getByTestId('jira-search-input');
    fireEvent.change(input, { target: { value: 'claims' } });
    expect(input.value).toBe('claims');

    // Wait past the 250ms debounce window using a real-timer sleep, then
    // waitFor polls until the refetch lands.
    await new Promise((r) => setTimeout(r, 400));
    await waitFor(() => {
      const calls = getProjectJiraTickets.mock.calls;
      const matched = calls.some((c) => c[1] && c[1].q === 'claims');
      expect(matched).toBe(true);
    }, { timeout: 3000 });
  });

  it('clicking a sortable header toggles asc/desc and re-fetches with the new params', async () => {
    getProjectJiraTickets.mockResolvedValue(listResp([row()]));
    getProjectJiraSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, counts: null });

    await act(async () => {
      renderAt();
    });
    await waitFor(() => {
      expect(screen.getByTestId('jira-col-title')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('jira-col-title'));
    });
    await waitFor(() => {
      const last = getProjectJiraTickets.mock.calls.at(-1);
      expect(last[1]).toMatchObject({ sort: 'title', order: 'desc' });
    });

    // Second click on the same column flips to asc.
    await act(async () => {
      fireEvent.click(screen.getByTestId('jira-col-title'));
    });
    await waitFor(() => {
      const last = getProjectJiraTickets.mock.calls.at(-1);
      expect(last[1]).toMatchObject({ sort: 'title', order: 'asc' });
    });
  });

  it('clicking a data row navigates to /projects/:pid/tickets/:ticket_id', async () => {
    getProjectJiraTickets.mockResolvedValue(listResp([row({ ticket_id: 1234, dwb_key: 'FRA-200' })]));
    getProjectJiraSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, counts: null });

    await act(async () => {
      renderAt();
    });
    await waitFor(() => {
      expect(screen.getByText('FRA-200')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('jira-row'));
    });
    expect(screen.getByTestId('ticket-detail-stub')).toBeInTheDocument();
  });

  it('manual sync button POSTs to the sync endpoint, refetches rows, and surfaces the last-sync summary', async () => {
    getProjectJiraTickets.mockResolvedValue(listResp([row()]));
    getProjectJiraSyncStatus
      .mockResolvedValueOnce({ status: 'idle', last_synced_at: null, counts: null })
      .mockResolvedValueOnce({
        status: 'done',
        last_synced_at: '2026-06-10T12:34:00',
        counts: { added: 3, updated: 1, unchanged: 5 },
      });
    triggerProjectJiraSync.mockResolvedValue({ status: 'done', started_at: '2026-06-10T12:34:00' });

    await act(async () => {
      renderAt();
    });
    await waitFor(() => {
      expect(screen.getByTestId('jira-sync-button')).toBeInTheDocument();
    });

    const button = screen.getByTestId('jira-sync-button');
    expect(button.textContent).toMatch(/\$ sync/);

    const initialCalls = getProjectJiraTickets.mock.calls.length;
    await act(async () => {
      fireEvent.click(button);
    });
    expect(triggerProjectJiraSync).toHaveBeenCalledWith(5);
    await waitFor(() => {
      expect(getProjectJiraTickets.mock.calls.length).toBeGreaterThan(initialCalls);
    });
    await waitFor(() => {
      expect(screen.getByTestId('jira-sync-summary').textContent).toMatch(/3 added \/ 1 updated \/ 5 unchanged/);
    });
  });

  it('renders the canonical tooltip-trigger info affordance next to the sync button with the read-only copy', async () => {
    getProjectJiraTickets.mockResolvedValue(listResp([row()]));
    getProjectJiraSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, counts: null });

    await act(async () => {
      renderAt();
    });

    await waitFor(() => {
      expect(screen.getByTestId('jira-sync-info')).toBeInTheDocument();
    });
    const info = screen.getByTestId('jira-sync-info');
    // Canonical pattern: <span class="tooltip-trigger">?<span class="tooltip-content">...</span></span>
    expect(info.tagName.toLowerCase()).toBe('span');
    expect(info.className).toMatch(/tooltip-trigger/);
    const content = info.querySelector('.tooltip-content');
    expect(content).toBeTruthy();
    expect(content.textContent).toMatch(/Pulls data from Jira into DWB\. Read-only - never modifies Jira\./);
  });

  it('Created and Updated cells render in dd-mm-yy hh:mm format (24h)', async () => {
    getProjectJiraTickets.mockResolvedValue(
      listResp([row({ created_at: '2026-06-05T09:00:00', updated_at: '2026-06-09T17:00:00' })])
    );
    getProjectJiraSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, counts: null });

    await act(async () => {
      renderAt();
    });

    await waitFor(() => {
      expect(screen.getByTestId('jira-row')).toBeInTheDocument();
    });

    // The two right-aligned cells in a row are Created + Updated. Assert the
    // FORMAT (two-digit groups joined by hyphens then colon) rather than the
    // exact value, since the displayed local hour depends on the test TZ.
    const cells = screen.getByTestId('jira-row').querySelectorAll('.jira-table__cell--right');
    expect(cells.length).toBeGreaterThanOrEqual(2);
    const pattern = /^\d{2}-\d{2}-\d{2} \d{2}:\d{2}$/;
    expect(cells[0].textContent.trim()).toMatch(pattern);
    expect(cells[1].textContent.trim()).toMatch(pattern);
  });

  it('on 409 the page flips to running state and polls until done', async () => {
    getProjectJiraTickets.mockResolvedValue(listResp([row()]));
    getProjectJiraSyncStatus
      .mockResolvedValueOnce({ status: 'idle', last_synced_at: null, counts: null }) // initial probe
      .mockResolvedValueOnce({ status: 'running', last_synced_at: null, counts: null }) // poll tick 1
      .mockResolvedValueOnce({
        status: 'done',
        last_synced_at: '2026-06-10T12:35:00',
        counts: { added: 0, updated: 2, unchanged: 7 },
      }); // poll tick 2 (completion)
    triggerProjectJiraSync.mockRejectedValue(new ApiError('already running', 409, null));

    await act(async () => {
      renderAt();
    });
    await waitFor(() => {
      expect(screen.getByTestId('jira-sync-button')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('jira-sync-button'));
    });
    // Button disabled while running.
    await waitFor(() => {
      expect(screen.getByTestId('jira-sync-button')).toBeDisabled();
    });
    expect(screen.getByTestId('jira-sync-summary').textContent).toMatch(/sync running/);

    // Advance poll ticks until completion.
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    await waitFor(() => {
      expect(screen.getByTestId('jira-sync-summary').textContent).toMatch(/2 updated \/ 7 unchanged/);
    });
    expect(screen.getByTestId('jira-sync-button')).not.toBeDisabled();
  });
});
