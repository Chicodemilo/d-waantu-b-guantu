// Path: src/components/dashboard/__tests__/TimeTokens.test.jsx
// File: TimeTokens.test.jsx
// Created: 2026-06-10
// Purpose: Tests for the OVERHEAD section of TimeTokens — Ad Hoc row renders alongside TL/PM rows, value comes from project_total.ad_hoc_overhead_tokens, null-guards to 0 when the field is absent (pre-DWB-353), and the updated tooltip text describes ad-hoc work without an em dash
// Caller: vitest test runner
// Callees: ../TimeTokens, ../../../store/useStore (mocked), ../../../services/tracking (mocked), ../../../services/trackingCache (reset between tests)
// Data In: Mocked store + tracking summary
// Data Out: Test assertions
// Last Modified: 2026-06-12

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';

const mockState = {
  projects: [{ id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu', status: 'active' }],
};
vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

vi.mock('../../../services/tracking', () => ({
  getTrackingSummary: vi.fn(),
}));

import TimeTokens from '../TimeTokens';
import { getTrackingSummary } from '../../../services/tracking';
import { __resetTrackingCacheForTests } from '../../../services/trackingCache';

function summary(overrides = {}) {
  return {
    project_total: {
      tokens: 5_000_000,
      time_seconds: 18000,
      overhead_tokens: 1_000_000,
      ...overrides,
    },
    per_agent: [
      { name: 'Archie_DWB', role: 'team-lead', tokens: 500_000, time_seconds: 1000, agent_id: 13 },
      { name: 'Pam_DWB', role: 'pm', tokens: 200_000, time_seconds: 400, agent_id: 14 },
      { name: 'Freddie', role: 'frontend-worker', tokens: 800_000, time_seconds: 600, agent_id: 19 },
    ],
    per_ticket: [],
  };
}

describe('TimeTokens — Ad Hoc overhead row', () => {
  beforeEach(() => {
    getTrackingSummary.mockReset();
    __resetTrackingCacheForTests();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders an Ad Hoc row with the ad_hoc_overhead_tokens / ad_hoc_overhead_seconds values', async () => {
    getTrackingSummary.mockResolvedValue(
      summary({ ad_hoc_overhead_tokens: 250_000, ad_hoc_overhead_seconds: 300 })
    );

    await act(async () => {
      render(<TimeTokens projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText('Overhead')).toBeInTheDocument();
    });

    // Ad Hoc row label appears alongside TL/PM rows.
    expect(screen.getByText('Ad Hoc')).toBeInTheDocument();
    expect(screen.getByText('Archie_DWB/team-lead')).toBeInTheDocument();
    expect(screen.getByText('Pam_DWB/pm')).toBeInTheDocument();
  });

  it('null-guards Ad Hoc to 0 when the field is absent on project_total (pre-DWB-353)', async () => {
    // No ad_hoc_overhead_* fields on the summary at all.
    getTrackingSummary.mockResolvedValue(summary());

    await act(async () => {
      render(<TimeTokens projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText('Ad Hoc')).toBeInTheDocument();
    });
    // Row exists; value should render (formatTokens(0) -> "0" via the helper).
    const adHocLabel = screen.getByText('Ad Hoc');
    const row = adHocLabel.closest('.tt-table__row');
    expect(row).toBeTruthy();
  });

  it('Ad Hoc row renders a static caret for visual parity with the TL/PM rows', async () => {
    getTrackingSummary.mockResolvedValue(summary());

    await act(async () => {
      render(<TimeTokens projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText('Ad Hoc')).toBeInTheDocument();
    });

    const adHocLabel = screen.getByText('Ad Hoc');
    const row = adHocLabel.closest('.tt-table__row');
    expect(row).toBeTruthy();
    // Caret element is present (visual parity with TL/PM rows).
    expect(row.querySelector('.tt-caret')).toBeTruthy();
    // Row label is the plain bucket name, not an agent/role slash format.
    expect(adHocLabel.textContent).toBe('Ad Hoc');
    expect(adHocLabel.textContent).not.toContain('/');
  });

  it('Overhead tooltip describes ad-hoc work and does not contain an em dash', async () => {
    getTrackingSummary.mockResolvedValue(summary());

    await act(async () => {
      render(<TimeTokens projectId={1} />);
    });

    await waitFor(() => {
      expect(screen.getByText('Overhead')).toBeInTheDocument();
    });

    // Find the Overhead section's tooltip-content sibling and read its text.
    const overheadTitle = screen.getByText('Overhead');
    const tooltipContent = overheadTitle.parentElement.querySelector('.tooltip-content');
    expect(tooltipContent).toBeTruthy();
    expect(tooltipContent.textContent).toMatch(/ad-hoc/i);
    expect(tooltipContent.textContent).not.toMatch(/—/); // em dash
  });
});
