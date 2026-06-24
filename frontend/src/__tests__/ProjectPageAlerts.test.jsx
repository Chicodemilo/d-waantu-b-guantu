// Path: src/__tests__/ProjectPageAlerts.test.jsx
// File: ProjectPageAlerts.test.jsx
// Created: 2026-06-24
// Purpose: Tests for the DWB-464 alert category filter + grouping in the ProjectPage alerts panel. Covers the category filter chips (with counts), grouping banners under per-category headers, and filtering to a single category on chip click.
// Caller: vitest test runner
// Callees: ../pages/ProjectPage, ../store/useStore (mocked w/ SURFACED_ALERT_CATEGORIES), ../api/projects (mocked), ../api/alerts (mocked), child components (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store project + alerts
// Data Out: Test assertions
// Last Modified: 2026-06-24

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/projects', () => ({
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  disableJira: vi.fn(),
  getGateStatus: vi.fn(),
}));

vi.mock('../api/alerts', () => ({
  dismissAllAlerts: vi.fn(),
  getAlerts: vi.fn(),
  sendAlertsToTeam: vi.fn(),
}));

vi.mock('../components/project/ProjectHeader', () => ({ default: () => null }));
vi.mock('../components/project/SprintProgress', () => ({ default: () => null }));
vi.mock('../components/dashboard/TimeTokens', () => ({ default: () => null }));
vi.mock('../components/sprints/SprintVelocity', () => ({ default: () => null }));
vi.mock('../components/epics/EpicList', () => ({ default: () => null }));
vi.mock('../components/project/ActivityFeed', () => ({ default: () => null }));
vi.mock('../components/project/LiveSessions', () => ({ default: () => null }));
vi.mock('../components/project/TokenBudget', () => ({ default: () => null }));
vi.mock('../components/project/ConsolidationStatus', () => ({ default: () => null }));
// Stub AlertBanner so we can read which alerts render per group.
vi.mock('../components/common/AlertBanner', () => ({
  default: ({ alert }) => (
    <div data-testid="banner" data-cat={alert.category}>{alert.id}</div>
  ),
}));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
  SURFACED_ALERT_CATEGORIES: ['comms', 'scoring', 'actionable'],
}));

import ProjectPage from '../pages/ProjectPage';

function seed(alerts) {
  mockState = {
    projects: [{ id: 1, prefix: 'DWB', name: 'DWB', status: 'active', repo_path: '/repo', force_headers: false, jira_project_key: null }],
    polling: { lastUpdated: 12345 },
    getTicketsByProject: () => [],
    setAlerts: vi.fn(),
    alerts,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/1']}>
      <Routes>
        <Route path="/projects/:id" element={<ProjectPage />} />
      </Routes>
    </MemoryRouter>
  );
}

const ALERTS = [
  { id: 1, project_id: 1, status: 'open', severity: 'warning', category: 'actionable', created_at: '2026-06-20T10:00:00Z' },
  { id: 2, project_id: 1, status: 'open', severity: 'critical', category: 'actionable', created_at: '2026-06-21T10:00:00Z' },
  { id: 3, project_id: 1, status: 'open', severity: 'info', category: 'comms', created_at: '2026-06-22T10:00:00Z' },
  { id: 4, project_id: 1, status: 'open', severity: 'info', category: 'scoring', created_at: '2026-06-23T10:00:00Z' },
];

beforeEach(() => seed(ALERTS));
afterEach(() => cleanup());

describe('ProjectPage alert category filter + grouping (DWB-464)', () => {
  it('renders a filter chip per present category plus an all chip with counts', () => {
    renderPage();
    expect(screen.getByRole('button', { name: /^all 4$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^comms 1$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^scoring 1$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^actionable 2$/ })).toBeInTheDocument();
  });

  it('groups banners under per-category titles (surfaced order) and shows all by default', () => {
    renderPage();
    const titles = Array.from(document.querySelectorAll('.alert-group__title')).map((t) => t.textContent);
    expect(titles).toEqual(['comms', 'scoring', 'actionable']);
    expect(screen.getAllByTestId('banner')).toHaveLength(4);
  });

  it('filters to a single category group when its chip is clicked', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /^actionable 2$/ }));
    const titles = Array.from(document.querySelectorAll('.alert-group__title')).map((t) => t.textContent);
    expect(titles).toEqual(['actionable']);
    const banners = screen.getAllByTestId('banner');
    expect(banners).toHaveLength(2);
    expect(banners.every((b) => b.getAttribute('data-cat') === 'actionable')).toBe(true);
  });
});
