// Path: src/__tests__/SessionDetailPage.test.jsx
// File: SessionDetailPage.test.jsx
// Created: 2026-06-10
// Purpose: Tests for SessionDetailPage — route resolves and fetches by :sid, full payload renders (header, methods, phrases, by_role, by_ticket, overhead), back link points to the sessions list, 404 path shows a session-not-found view with back navigation, polling cease on closed sessions. DWBG-022: narrative refs become clickable repo links (file, file:line, commit sha) when the session's project has a repo_url, and stay styled non-clickable text when repo_url is null. DWBG-023: a source-aware "back to search" affordance appears only when the user arrived from the cross-project Recall page (location.state.from='recall').
// Caller: vitest test runner
// Callees: ../pages/SessionDetailPage, ../api/sessions (mocked), ../api/projects (mocked), ../api/client (ApiError), ../store/useStore (mocked)
// Data In: Mocked sessions API + projects API + store selectors
// Data Out: Test assertions
// Last Modified: 2026-06-25 (DWBG-022 narrative ref links; DWBG-023 source-aware back-nav)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/sessions', () => ({
  getProjectSessions: vi.fn(),
  getSession: vi.fn(),
}));

vi.mock('../api/projects', () => ({
  getProject: vi.fn(),
}));

let mockProject = { id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu' };
vi.mock('../store/useStore', () => ({
  default: (selector) => selector({ getProject: () => mockProject }),
}));

import SessionDetailPage from '../pages/SessionDetailPage';
import { getSession } from '../api/sessions';
import { getProject } from '../api/projects';
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

function renderAt(path, state) {
  const entry = state ? { pathname: path, state } : path;
  return render(
    <MemoryRouter initialEntries={[entry]}>
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
    getProject.mockReset();
    // Default: project read with no remote, so narrative refs stay plain text
    // unless a test opts into a repo_url.
    getProject.mockResolvedValue({ id: 1, prefix: 'DWB', repo_url: null });
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

  // DWBG-022: clickable code/commit references in the narrative.
  describe('DWBG-022 narrative ref links', () => {
    // A narrative whose bullets carry a file ref, a file:line ref, and a commit sha.
    function narrativeDetail(overrides = {}) {
      return closedDetail({
        narrative: {
          lead: 'Touched app/main.py and shipped commit 1a2b3c4d5e6f7081.',
          sections: [
            {
              title: 'Changes',
              bullets: [
                'Edited src/components/project/InlineMarkdown.jsx',
                'Fixed the bug at app/services/sprint.py:142',
                'Landed in commit deadbeef1234567',
              ],
            },
          ],
        },
        narrative_author: 'Archie_DWB',
        narrative_generated_at: '2026-06-25T12:00:00',
        ...overrides,
      });
    }

    it('renders file, file:line, and commit refs as repo links when repo_url is present', async () => {
      getSession.mockResolvedValue(narrativeDetail());
      getProject.mockResolvedValue({
        id: 1,
        prefix: 'DWB',
        repo_url: 'https://github.com/acme/dwb',
      });

      await act(async () => {
        renderAt('/projects/1/sessions/4');
      });

      await waitFor(() => {
        expect(screen.getByText(/DWB Session #4/)).toBeInTheDocument();
      });
      // repo_url fetch resolves -> refs become anchors.
      await waitFor(() => {
        expect(
          screen.getByText('src/components/project/InlineMarkdown.jsx').closest('a')
        ).not.toBeNull();
      });

      // file ref -> blob/HEAD/{path}
      const fileLink = screen
        .getByText('src/components/project/InlineMarkdown.jsx')
        .closest('a');
      expect(fileLink.getAttribute('href')).toBe(
        'https://github.com/acme/dwb/blob/HEAD/src/components/project/InlineMarkdown.jsx'
      );
      expect(fileLink.getAttribute('target')).toBe('_blank');
      expect(fileLink.getAttribute('rel')).toBe('noopener noreferrer');

      // file:line ref -> blob/HEAD/{path}#L{line}
      const lineLink = screen.getByText('app/services/sprint.py:142').closest('a');
      expect(lineLink.getAttribute('href')).toBe(
        'https://github.com/acme/dwb/blob/HEAD/app/services/sprint.py#L142'
      );

      // commit sha -> commit/{sha}
      const shaLink = screen.getByText('deadbeef1234567').closest('a');
      expect(shaLink.getAttribute('href')).toBe(
        'https://github.com/acme/dwb/commit/deadbeef1234567'
      );
      expect(shaLink.getAttribute('rel')).toBe('noopener noreferrer');
    });

    it('renders refs as styled non-clickable text when repo_url is null', async () => {
      getSession.mockResolvedValue(narrativeDetail());
      getProject.mockResolvedValue({ id: 1, prefix: 'DWB', repo_url: null });

      await act(async () => {
        renderAt('/projects/1/sessions/4');
      });

      await waitFor(() => {
        expect(screen.getByText(/DWB Session #4/)).toBeInTheDocument();
      });
      await waitFor(() => {
        expect(getProject).toHaveBeenCalled();
      });

      // No anchor for any of the refs; they render as styled spans.
      const fileNode = screen.getByText('src/components/project/InlineMarkdown.jsx');
      expect(fileNode.closest('a')).toBeNull();
      expect(fileNode).toHaveClass('narrative-ref');

      const shaNode = screen.getByText('deadbeef1234567');
      expect(shaNode.closest('a')).toBeNull();
      expect(shaNode).toHaveClass('narrative-ref');

      // And no undefined/broken hrefs leaked into the document.
      expect(document.querySelector('a[href*="undefined"]')).toBeNull();
    });
  });

  // DWBG-023: source-aware "back to search" affordance.
  describe('DWBG-023 source-aware back-nav', () => {
    it('shows a back-to-search link when arriving from recall, pointing at the preserved query', async () => {
      getSession.mockResolvedValue(closedDetail());

      await act(async () => {
        renderAt('/projects/1/sessions/4', {
          from: 'recall',
          recallSearch: '?q=migration&project_id=1',
        });
      });

      await waitFor(() => {
        expect(screen.getByText(/DWB Session #4/)).toBeInTheDocument();
      });

      const back = screen.getByTestId('back-to-recall');
      expect(back.getAttribute('href')).toBe('/sessions?q=migration&project_id=1');
    });

    it('does NOT show a back-to-search link when arriving from the per-project list', async () => {
      getSession.mockResolvedValue(closedDetail());

      await act(async () => {
        renderAt('/projects/1/sessions/4'); // no router state -> not from recall
      });

      await waitFor(() => {
        expect(screen.getByText(/DWB Session #4/)).toBeInTheDocument();
      });

      expect(screen.queryByTestId('back-to-recall')).toBeNull();
      // The normal per-project sessions breadcrumb is still present.
      const backLinks = screen.getAllByRole('link', { name: /sessions/ });
      expect(backLinks.some((a) => a.getAttribute('href') === '/projects/1/sessions')).toBe(true);
    });
  });
});
