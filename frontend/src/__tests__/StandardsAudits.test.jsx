// Path: src/__tests__/StandardsAudits.test.jsx
// File: StandardsAudits.test.jsx
// Created: 2026-08-12
// Purpose: Tests for the Standards Audits project-page section (DWB-018). Covers rendering a PASS audit, a REJECT audit with a non-empty violations list + per-agent scorecard, and the empty state when a project has no audits.
// Caller: vitest test runner
// Callees: ../components/project/StandardsAudits, ../api/standardsAudits (mocked)
// Data In: Mocked getStandardsAudits responses
// Data Out: Test assertions
// Last Modified: 2026-08-12 (DWB-018)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';

vi.mock('../api/standardsAudits', () => ({
  getStandardsAudits: vi.fn(),
}));

import StandardsAudits from '../components/project/StandardsAudits';
import { getStandardsAudits } from '../api/standardsAudits';

const passAudit = {
  id: 11,
  verdict: 'pass',
  pr_ref: 'staged@1991de9',
  diff_range: 'staged',
  violations: [],
  scorecard: [{ agent: 'Barry_DWB', delta: 2, reason: 'clean service encapsulation' }],
  run_at: '2026-08-11T20:20:21',
  triggered_by: 'auditor_script',
};

const rejectAudit = {
  id: 10,
  verdict: 'reject',
  pr_ref: 'staged@abc1234',
  diff_range: 'staged',
  violations: [
    {
      file: 'backend/app/services/playbook_deploy.py',
      line: 415,
      note: 'Edited without updating the Last Modified header field.',
      rule: 'Headers',
      severity: 'medium',
    },
  ],
  scorecard: [{ agent: 'Barry_DWB', delta: -1, reason: 'missing Last Modified bump' }],
  run_at: '2026-08-11T19:00:00',
  triggered_by: 'auditor_script',
};

beforeEach(() => {
  getStandardsAudits.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('StandardsAudits section (DWB-018)', () => {
  it('renders a PASS verdict audit with its PR ref', async () => {
    getStandardsAudits.mockResolvedValue([passAudit]);
    render(<StandardsAudits projectId={5} />);

    expect(await screen.findByText('PASS')).toBeInTheDocument();
    expect(screen.getByText('staged@1991de9')).toBeInTheDocument();
    expect(screen.getByText('Barry_DWB')).toBeInTheDocument();
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('renders a REJECT audit with its violations and scorecard', async () => {
    getStandardsAudits.mockResolvedValue([rejectAudit]);
    render(<StandardsAudits projectId={5} />);

    expect(await screen.findByText('REJECT')).toBeInTheDocument();
    // violation: rule + file:line + note
    expect(screen.getByText('Headers')).toBeInTheDocument();
    expect(screen.getByText('backend/app/services/playbook_deploy.py:415')).toBeInTheDocument();
    expect(
      screen.getByText('Edited without updating the Last Modified header field.')
    ).toBeInTheDocument();
    // scorecard: agent + negative delta + reason
    expect(screen.getByText('-1')).toBeInTheDocument();
    expect(screen.getByText('missing Last Modified bump')).toBeInTheDocument();
  });

  it('renders the empty state when the project has no audits', async () => {
    getStandardsAudits.mockResolvedValue([]);
    render(<StandardsAudits projectId={5} />);

    expect(await screen.findByText('No audits yet')).toBeInTheDocument();
  });
});
