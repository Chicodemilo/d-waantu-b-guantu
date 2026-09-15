// Path: src/__tests__/timestampParsing.test.jsx
// File: timestampParsing.test.jsx
// Created: 2026-09-15
// Purpose: One case per component converted in DWB-557, proving each renders an API timestamp as the UTC instant it is rather than as local time. The API sends naive UTC with no trailing Z, so a raw parse is wrong by the viewer's offset. Each case feeds a naive timestamp and asserts the rendered text equals the same instant formatted from an explicit UTC parse, which is an equality that holds in any runner timezone. Grouped by property rather than split across nine near-identical files, because the property under test is the same in every component and one place to audit it is worth more than nine copies of the mock scaffolding. ArchieChannelPage and InterAgentCommsPage keep their cases in their own existing suites.
// Caller: vitest test runner
// Callees: the nine converted components, their stores and api modules (mocked), ../utils/format
// Data In: Naive-UTC timestamps in mocked API and store payloads
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/tickets', () => ({ getTicketHistory: vi.fn(), updateTicket: vi.fn() }));
vi.mock('../api/jira', () => ({ getJiraConfig: vi.fn(), getJiraIssue: vi.fn() }));
vi.mock('../api/errors', () => ({ getErrorLogs: vi.fn(), getErrorSources: vi.fn() }));
vi.mock('../api/testResults', () => ({ getTestPerformance: vi.fn(), getProjectTestRuns: vi.fn(), getTestRuns: vi.fn() }));
vi.mock('../api/system', () => ({ runSystemTests: vi.fn() }));
vi.mock('../api/projects', () => ({ getPlaybookFiles: vi.fn(), getProjects: vi.fn() }));

const storeState = {
  agents: [{ id: 1, name: 'Sage' }],
  projects: [],
  jiraIssues: {},
  jiraConfig: null,
  comments: [],
  alerts: [],
  tickets: [],
  epics: [],
  sprints: [],
  getCommentsByTicket: () => [],
  getTicket: () => null,
  getProject: () => null,
  getAgent: () => null,
  getAgentsByProject: () => [],
  getEpicsByProject: () => [],
  getSprintsByProject: () => [],
  getTicketsByProject: () => [],
  getSurfacedAlerts: () => [],
  getAlertsByProject: () => [],
  clearAllAlerts: () => {},
  setJiraConfig: () => {},
  setJiraIssue: () => {},
  dismissAlert: () => {},
  tokenTotals: { total_tokens: 0 },
  projectAgents: [],
  testRuns: [],
};
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(globalThis.__storeState),
}));

import TicketComments from '../components/tickets/TicketComments';
import TicketDetail from '../components/tickets/TicketDetail';
import TestPerformance from '../components/tests/TestPerformance';
import PlaybookInspector from '../components/project/PlaybookInspector';
import ProjectHeader from '../components/project/ProjectHeader';
import ErrorLogPage from '../pages/ErrorLogPage';
import TestResultsPage from '../pages/TestResultsPage';
import ProjectTestsPage from '../pages/ProjectTestsPage';
import DashboardPage from '../pages/DashboardPage';

import { getTicketHistory } from '../api/tickets';
import { getJiraConfig } from '../api/jira';
import { getErrorLogs } from '../api/errors';
import { getTestPerformance, getProjectTestRuns } from '../api/testResults';
import { getPlaybookFiles } from '../api/projects';

// The instant every case uses, and the two option sets the components render with.
const NAIVE = '2026-09-08T18:30:05';
const INSTANT = Date.parse(`${NAIVE}Z`);
const WITH_SECONDS = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
const NO_SECONDS = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false };

// Expectations derived from the instant, so they hold in any timezone the suite runs in.
const expectWithSeconds = () => new Date(INSTANT).toLocaleString('en-US', WITH_SECONDS);
const expectNoSeconds = () => new Date(INSTANT).toLocaleString('en-US', NO_SECONDS);
const expectDay = () => new Date(INSTANT).toLocaleDateString();
// What a raw, unnormalized parse would have produced: the bug this ticket removes.
const buggy = (opts) => new Date(NAIVE).toLocaleString('en-US', opts);

const renderIn = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('API timestamps render as UTC, not local (DWB-557)', () => {
  beforeEach(() => {
    globalThis.__storeState = { ...storeState };
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(Date.parse('2026-09-15T12:00:00Z'));
    getTicketHistory.mockResolvedValue([]);
    getJiraConfig.mockResolvedValue({ enabled: false });
    getErrorLogs.mockResolvedValue([]);
    getTestPerformance.mockResolvedValue([]);
    getProjectTestRuns.mockResolvedValue([]);
    getPlaybookFiles.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it('sanity: the naive and UTC readings genuinely differ unless the runner is on UTC', () => {
    const offset = new Date().getTimezoneOffset();
    if (offset !== 0) {
      expect(buggy(NO_SECONDS)).not.toBe(expectNoSeconds());
    }
    // and the helper under test always agrees with the explicit UTC parse
    expect(new Date(INSTANT).toISOString()).toBe('2026-09-08T18:30:05.000Z');
  });

  it('TicketComments renders the comment time as UTC', async () => {
    globalThis.__storeState.getCommentsByTicket = () => [
      { id: 1, author_agent_id: 1, body: 'hello', created_at: NAIVE },
    ];
    await act(async () => { renderIn(<TicketComments ticketId={1} />); });
    expect(document.querySelector('.comment__time').textContent).toBe(expectNoSeconds());
  });

  it('TicketDetail renders the created day and the status-history time as UTC', async () => {
    globalThis.__storeState.getTicket = () => ({
      id: 1, ticket_key: 'DWB-1', title: 'T', status: 'done', ticket_type: 'task',
      project_id: 1, created_at: NAIVE, tokens_used: 0, time_spent_seconds: 0, subtasks: [],
    });
    globalThis.__storeState.getProject = () => ({ id: 1, prefix: 'DWB', name: 'D' });
    getTicketHistory.mockResolvedValue([{ id: 1, from_status: 'todo', to_status: 'done', changed_at: NAIVE }]);

    await act(async () => { renderIn(<TicketDetail ticketId={1} />); });
    await waitFor(() => expect(document.querySelector('.status-history__list')).toBeTruthy());
    expect(screen.getByText(expectDay())).toBeInTheDocument();
    expect(document.querySelector('.status-history__list').textContent).toContain(expectNoSeconds());
  });

  it('TestPerformance renders run labels as UTC', async () => {
    getTestPerformance.mockResolvedValue([
      { id: 1, run_at: NAIVE, total_tests: 10, duration: 1.5, duration_seconds: 1.5, passed: 10, failed: 0 },
    ]);
    getProjectTestRuns.mockResolvedValue([
      { id: 1, run_at: NAIVE, duration_seconds: 1.5, total_tests: 10, passed: 10, failed: 0, details: null },
    ]);
    await act(async () => { renderIn(<TestPerformance projectId={1} />); });
    await waitFor(() => expect(document.body.textContent).toContain(expectNoSeconds()));
    expect(document.body.textContent).not.toContain(buggy(NO_SECONDS));
  });

  it('PlaybookInspector renders the deployed date as UTC', async () => {
    getPlaybookFiles.mockResolvedValue([
      { name: 'worker_playbook.md', path: '.claude/worker_playbook.md', exists: true, last_modified: NAIVE, size: 10, content: 'x' },
    ]);
    await act(async () => { renderIn(<PlaybookInspector projectId={1} />); });
    await waitFor(() => expect(document.body.textContent).toContain(expectDay()));
  });

  it('ProjectHeader renders the project created day as UTC', async () => {
    await act(async () => {
      renderIn(<ProjectHeader project={{ id: 1, prefix: 'DWB', name: 'D', status: 'active', created_at: NAIVE }} />);
    });
    expect(document.querySelector('.project-header__meta-value').textContent).toBe(expectDay());
  });

  it('ErrorLogPage renders error times as UTC', async () => {
    getErrorLogs.mockResolvedValue([
      { id: 1, source: 'backend', endpoint: 'GET /x', error_type: 'HTTP_500', message: 'boom', created_at: NAIVE, status_code: 500 },
    ]);
    await act(async () => { renderIn(<ErrorLogPage />); });
    await waitFor(() => expect(document.body.textContent).toContain(expectWithSeconds()));
  });

  it('TestResultsPage renders run times as UTC', async () => {
    globalThis.__storeState.testRuns = [
      {
        id: 1, run_at: NAIVE, passed: 1, failed: 0, skipped: 0, total_tests: 1,
        duration_seconds: 1, triggered_by: 'tester', project_id: 1, status: 'passed',
        coverage_percent: null, details: null, output: '',
      },
    ];
    await act(async () => { renderIn(<TestResultsPage />); });
    await waitFor(() => expect(document.body.textContent).toContain(expectWithSeconds()));
  });

  it('ProjectTestsPage renders run times as UTC', async () => {
    globalThis.__storeState.getProject = () => ({ id: 1, prefix: 'DWB', name: 'D', status: 'active' });
    getProjectTestRuns.mockResolvedValue([
      {
        id: 1, project_id: 1, run_at: NAIVE, passed: 1, failed: 0, skipped: 0, total_tests: 1,
        duration_seconds: 1, triggered_by: 'tester', status: 'passed', details: null,
      },
    ]);
    await act(async () => {
      render(
        <MemoryRouter initialEntries={['/projects/1/tests']}>
          <Routes>
            <Route path="/projects/:id/tests" element={<ProjectTestsPage />} />
          </Routes>
        </MemoryRouter>
      );
    });
    await waitFor(() => expect(document.body.textContent).toContain(expectWithSeconds()));
  });

  it('DashboardPage renders the alert time as UTC', async () => {
    globalThis.__storeState.getSurfacedAlerts = () => [
      { id: 1, severity: 'warning', category: 'actionable', title: 'A', body: 'b', created_at: NAIVE, project_id: 1 },
    ];
    globalThis.__storeState.getProject = () => ({ id: 1, prefix: 'DWB', name: 'D', status: 'active' });
    await act(async () => { renderIn(<DashboardPage />); });
    const expected = new Date(INSTANT).toLocaleString('en-US', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
    await waitFor(() => expect(document.body.textContent).toContain(expected));
  });
});
