// Path: src/__tests__/AuditsPage.test.jsx
// File: AuditsPage.test.jsx
// Created: 2026-08-12
// Purpose: Tests for the project-level Audits page (DWB-031). Covers the summary math (total, pass/reject counts, pass %), row rendering, expand/collapse revealing violations + scorecard, and the empty state. Exercises the shared common/ audit render pieces at their AuditsPage call site.
// Caller: vitest test runner
// Callees: ../pages/AuditsPage, ../store/useStore (mocked), ../api/standardsAudits (mocked via the hook), react-router-dom (MemoryRouter)
// Data In: Mocked store project + mocked getStandardsAudits responses
// Data Out: Test assertions
// Last Modified: 2026-08-12 (DWB-031)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/standardsAudits', () => ({
  getStandardsAudits: vi.fn(),
}));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import AuditsPage from '../pages/AuditsPage';
import { getStandardsAudits } from '../api/standardsAudits';

function seed() {
  mockState = {
    projects: [{ id: 5, prefix: 'DWB', name: 'D Waantu B Guantu', repo_path: '/repo/dwb' }],
  };
}

const audits = [
  { id: 1, verdict: 'pass', pr_ref: 'staged@aaa', run_at: '2026-08-11T20:00:00', violations: [], scorecard: [{ agent: 'Barry_DWB', delta: 2, reason: 'clean encapsulation' }] },
  { id: 2, verdict: 'pass', pr_ref: 'staged@bbb', run_at: '2026-08-11T20:05:00', violations: [], scorecard: [] },
  {
    id: 3,
    verdict: 'reject',
    pr_ref: 'staged@ccc',
    triggered_by: 'auditor_script',
    run_at: '2026-08-11T20:10:00',
    violations: [{ rule: 'Headers', severity: 'medium', file: 'x.py', line: 10, note: 'missing header bump' }],
    scorecard: [{ agent: 'Barry_DWB', delta: -1, reason: 'no last modified' }],
  },
];

beforeEach(() => {
  getStandardsAudits.mockReset();
  seed();
});

afterEach(() => {
  cleanup();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/5/audits']}>
      <Routes>
        <Route path="/projects/:id/audits" element={<AuditsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AuditsPage (DWB-031)', () => {
  it('renders summary stats with the pass percentage', async () => {
    getStandardsAudits.mockResolvedValue(audits);
    renderPage();

    // 2 pass of 3 -> 67% pass, 33% fail
    expect(await screen.findByText('67%')).toBeInTheDocument();
    expect(screen.getByText('33%')).toBeInTheDocument();
    expect(screen.getByText('pass rate')).toBeInTheDocument();
    expect(screen.getByText('fail rate')).toBeInTheDocument();
  });

  it('renders a row per audit and expands in place to show violations + scorecard', async () => {
    getStandardsAudits.mockResolvedValue(audits);
    renderPage();

    // rows render with their refs
    const refCell = await screen.findByText('staged@ccc');
    // detail is hidden until expanded
    expect(screen.queryByText('missing header bump')).not.toBeInTheDocument();

    fireEvent.click(refCell.closest('button'));

    // expanded detail: who + violation + scorecard
    expect(screen.getByText(/Triggered by: auditor_script/)).toBeInTheDocument();
    expect(screen.getByText('Headers')).toBeInTheDocument();
    expect(screen.getByText('x.py:10')).toBeInTheDocument();
    expect(screen.getByText('missing header bump')).toBeInTheDocument();
    expect(screen.getByText('no last modified')).toBeInTheDocument();
    expect(screen.getByText('-1')).toBeInTheDocument();

    // collapse
    fireEvent.click(refCell.closest('button'));
    expect(screen.queryByText('missing header bump')).not.toBeInTheDocument();
  });

  it('renders the empty state when the project has no audits', async () => {
    getStandardsAudits.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByTestId('audits-empty')).toHaveTextContent('No audits yet');
  });
});
