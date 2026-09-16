// Path: src/__tests__/TestResultsPage.test.jsx
// File: TestResultsPage.test.jsx
// Created: 2026-09-16
// Purpose: DWB-571 - the global /tests page has no :id route param, so it has to find the one project this server can honestly run tests for itself (the project whose runs_own_tests is true) and pass THAT id to runSystemTests, never a default. Pins: button disabled when no such project exists, and the id actually sent when one does.
// Caller: vitest test runner
// Callees: ../pages/TestResultsPage, ../store/useStore (mocked), ../api/system (mocked), ../components/tests/TestCoverage (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store projects/testRuns + mocked api modules
// Data Out: Test assertions
// Last Modified: 2026-09-16 (DWB-571)

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/system', () => ({
  runSystemTests: vi.fn(),
}));

// Fetches its own data; not the point of this test.
vi.mock('../components/tests/TestCoverage', () => ({ default: () => null }));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import TestResultsPage from '../pages/TestResultsPage';
import { runSystemTests } from '../api/system';

const SELF_PROJECT_ID = 7;

function seed({ hasSelfProject } = {}) {
  mockState = {
    testRuns: [],
    projects: hasSelfProject
      ? [
          { id: 1, prefix: 'OTHER', runs_own_tests: false },
          { id: SELF_PROJECT_ID, prefix: 'DWB', runs_own_tests: true },
        ]
      : [{ id: 1, prefix: 'OTHER', runs_own_tests: false }],
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/tests']}>
      <Routes>
        <Route path="/tests" element={<TestResultsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('TestResultsPage run-tests control (DWB-571)', () => {
  afterEach(() => {
    cleanup();
    runSystemTests.mockReset();
  });

  it('disables the button when no project.runs_own_tests exists', () => {
    // With no test runs, both the header button and the empty-state prompt
    // button render (same label) - both must be disabled.
    seed({ hasSelfProject: false });
    renderPage();
    const buttons = screen.getAllByRole('button', { name: /run system tests/i });
    expect(buttons.length).toBeGreaterThan(0);
    buttons.forEach((b) => expect(b).toBeDisabled());
  });

  it('enables the button and calls runSystemTests with the self project id, not a default', async () => {
    seed({ hasSelfProject: true });
    runSystemTests.mockResolvedValue({ passed: 1, failed: 0, total: 1 });
    renderPage();
    const [button] = screen.getAllByRole('button', { name: /run system tests/i });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    await waitFor(() => {
      expect(runSystemTests).toHaveBeenCalledWith(SELF_PROJECT_ID);
    });
  });
});
