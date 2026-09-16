// Path: src/__tests__/ProjectTestsPage.test.jsx
// File: ProjectTestsPage.test.jsx
// Created: 2026-09-16
// Purpose: DWB-571 - the "run system tests" control on a project's Tests page must render only when project.runs_own_tests is true (the backend's answer, not a frontend recomputation), and clicking it must send THAT project's own id, not a default. Pins both the hide behavior and the id actually sent, so a regression that restores the button unconditionally, or that calls runSystemTests() with no argument, fails this test.
// Caller: vitest test runner
// Callees: ../pages/ProjectTestsPage, ../store/useStore (mocked), ../api/testResults (mocked), ../api/system (mocked), ../components/tests/TestPerformance + FailureAnalysis (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store project + mocked api modules
// Data Out: Test assertions
// Last Modified: 2026-09-16 (DWB-571: added a test asserting runSystemTests is called with the viewed project's own id, using a non-1 id so it can't pass by coincidence with the endpoint's old default)

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/testResults', () => ({
  getProjectTestRuns: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/system', () => ({
  runSystemTests: vi.fn(),
}));

// Heavy children fetch their own data; stub them out so this test stays
// focused on the run-tests control's visibility.
vi.mock('../components/tests/TestPerformance', () => ({ default: () => null }));
vi.mock('../components/tests/FailureAnalysis', () => ({ default: () => null }));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import ProjectTestsPage from '../pages/ProjectTestsPage';
import { runSystemTests } from '../api/system';

// A deliberately non-1 id: the endpoint's old default was project_id=1, so a
// bug that drops the argument and falls back to that default would still
// pass a test written against id 1. Using 42 makes that bug visible.
const PROJECT_ID = 42;

function project(overrides = {}) {
  return {
    id: PROJECT_ID,
    prefix: 'DWB',
    name: 'DWB',
    repo_path: '/repo',
    runs_own_tests: false,
    ...overrides,
  };
}

function seed(proj) {
  mockState = {
    projects: [proj],
    getProject: (id) => mockState.projects.find((p) => p.id === Number(id)),
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}/tests`]}>
      <Routes>
        <Route path="/projects/:id/tests" element={<ProjectTestsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ProjectTestsPage run-tests control (DWB-571)', () => {
  afterEach(() => {
    cleanup();
    runSystemTests.mockReset();
  });

  it('hides the button when runs_own_tests is false', async () => {
    seed(project({ runs_own_tests: false }));
    renderPage();
    await screen.findByText(/Test Results/i);
    expect(
      screen.queryByRole('button', { name: /run system tests/i })
    ).not.toBeInTheDocument();
  });

  it('shows the button when runs_own_tests is true', async () => {
    seed(project({ runs_own_tests: true }));
    renderPage();
    expect(
      await screen.findByRole('button', { name: /run system tests/i })
    ).toBeInTheDocument();
  });

  it('calls runSystemTests with the VIEWED project\'s own id, not a default', async () => {
    runSystemTests.mockResolvedValue({ passed: 1, failed: 0, total: 1 });
    seed(project({ runs_own_tests: true }));
    renderPage();
    const button = await screen.findByRole('button', { name: /run system tests/i });
    fireEvent.click(button);
    await waitFor(() => {
      expect(runSystemTests).toHaveBeenCalledWith(PROJECT_ID);
    });
  });
});
