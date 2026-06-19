// Path: src/__tests__/ProjectPageGates.test.jsx
// File: ProjectPageGates.test.jsx
// Created: 2026-06-19
// Purpose: Tests for DWB-400 force_consolidation gate toggle on ProjectPage. Covers: toggle renders with ON/OFF state, persists via updateProject PATCH on click, and the token-cost warning shows only when the gate is ON.
// Caller: vitest test runner
// Callees: ../pages/ProjectPage, ../store/useStore (mocked), ../api/projects (mocked), ../api/alerts (mocked), child components (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store project + mocked api modules
// Data Out: Test assertions
// Last Modified: 2026-06-19

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/projects', () => ({
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  disableJira: vi.fn(),
}));

vi.mock('../api/alerts', () => ({
  dismissAllAlerts: vi.fn(),
  getAlerts: vi.fn(),
  sendAlertsToTeam: vi.fn(),
}));

// Heavy children fetch their own data; stub them out so this test stays focused on the gates.
vi.mock('../components/project/ProjectHeader', () => ({ default: () => null }));
vi.mock('../components/project/SprintProgress', () => ({ default: () => null }));
vi.mock('../components/dashboard/TimeTokens', () => ({ default: () => null }));
vi.mock('../components/sprints/SprintVelocity', () => ({ default: () => null }));
vi.mock('../components/epics/EpicList', () => ({ default: () => null }));
vi.mock('../components/common/AlertBanner', () => ({ default: () => null }));
vi.mock('../components/project/ActivityFeed', () => ({ default: () => null }));
vi.mock('../components/project/LiveSessions', () => ({ default: () => null }));
vi.mock('../components/project/TokenBudget', () => ({ default: () => null }));
vi.mock('../components/project/ConsolidationStatus', () => ({ default: () => null }));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import ProjectPage from '../pages/ProjectPage';
import { updateProject } from '../api/projects';

const COST_TEXT = /Token cost: every project agent runs a consolidation pass at sprint close\./i;

function project(overrides = {}) {
  return {
    id: 1,
    prefix: 'DWB',
    name: 'DWB',
    status: 'active',
    repo_path: '/repo',
    force_headers: false,
    force_test_coverage: false,
    force_test_run: false,
    force_consolidation: false,
    force_initial_md: false,
    force_architecture_md: false,
    force_handoff_md: false,
    jira_project_key: null,
    ...overrides,
  };
}

function seed(proj) {
  mockState = {
    projects: [proj],
    polling: { lastUpdated: 12345 },
    getTicketsByProject: () => [],
    setAlerts: vi.fn(),
    alerts: [],
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

describe('ProjectPage force_consolidation gate (DWB-400)', () => {
  beforeEach(() => {
    updateProject.mockReset();
    updateProject.mockResolvedValue({});
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the consolidation toggle reflecting OFF state', () => {
    seed(project({ force_consolidation: false }));
    renderPage();
    expect(
      screen.getByRole('button', { name: /Consolidation at sprint close \[OFF\]/i })
    ).toBeInTheDocument();
  });

  it('renders the consolidation toggle reflecting ON state', () => {
    seed(project({ force_consolidation: true }));
    renderPage();
    expect(
      screen.getByRole('button', { name: /Consolidation at sprint close \[ON\]/i })
    ).toBeInTheDocument();
  });

  it('hides the token-cost warning when the gate is OFF', () => {
    seed(project({ force_consolidation: false }));
    renderPage();
    expect(screen.queryByText(COST_TEXT)).not.toBeInTheDocument();
  });

  it('shows the token-cost warning when the gate is ON', () => {
    seed(project({ force_consolidation: true }));
    renderPage();
    expect(screen.getByText(COST_TEXT)).toBeInTheDocument();
  });

  it('persists via updateProject PATCH (OFF -> ON) on click', async () => {
    seed(project({ force_consolidation: false }));
    renderPage();
    fireEvent.click(
      screen.getByRole('button', { name: /Consolidation at sprint close \[OFF\]/i })
    );
    await waitFor(() => {
      expect(updateProject).toHaveBeenCalledWith('1', { force_consolidation: true });
    });
  });
});

const HEADERS_COST_TEXT = /Token cost: a code-header block is required on every new or changed source file\./i;

describe('ProjectPage force_headers gate (DWB-403)', () => {
  beforeEach(() => {
    updateProject.mockReset();
    updateProject.mockResolvedValue({});
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the Force Headers toggle reflecting OFF state', () => {
    seed(project({ force_headers: false }));
    renderPage();
    expect(
      screen.getByRole('button', { name: /Force Headers \[OFF\]/i })
    ).toBeInTheDocument();
  });

  it('renders the Force Headers toggle reflecting ON state', () => {
    seed(project({ force_headers: true }));
    renderPage();
    expect(
      screen.getByRole('button', { name: /Force Headers \[ON\]/i })
    ).toBeInTheDocument();
  });

  it('hides the token-cost warning when the gate is OFF', () => {
    seed(project({ force_headers: false }));
    renderPage();
    expect(screen.queryByText(HEADERS_COST_TEXT)).not.toBeInTheDocument();
  });

  it('shows the token-cost warning when the gate is ON', () => {
    seed(project({ force_headers: true }));
    renderPage();
    expect(screen.getByText(HEADERS_COST_TEXT)).toBeInTheDocument();
  });

  it('persists via updateProject PATCH (OFF -> ON) on click', async () => {
    seed(project({ force_headers: false }));
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /Force Headers \[OFF\]/i }));
    await waitFor(() => {
      expect(updateProject).toHaveBeenCalledWith('1', { force_headers: true });
    });
  });
});
