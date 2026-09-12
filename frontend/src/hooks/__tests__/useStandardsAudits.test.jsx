// Path: src/hooks/__tests__/useStandardsAudits.test.jsx
// File: useStandardsAudits.test.jsx
// Created: 2026-08-12
// Purpose: Tests for the useStandardsAudits view-shaped hook (DWB-018). Covers the loading -> loaded transition returning the audits array, and the error path setting error true when the fetch rejects.
// Caller: vitest test runner
// Callees: ../useStandardsAudits, ../../api/standardsAudits (mocked)
// Data In: Mocked getStandardsAudits responses
// Data Out: Test assertions
// Last Modified: 2026-08-12 (DWB-018)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, cleanup } from '@testing-library/react';

vi.mock('../../api/standardsAudits', () => ({
  getStandardsAudits: vi.fn(),
}));

import useStandardsAudits from '../useStandardsAudits';
import { getStandardsAudits } from '../../api/standardsAudits';

beforeEach(() => {
  getStandardsAudits.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('useStandardsAudits (DWB-018)', () => {
  it('starts loading, then returns the fetched audits', async () => {
    getStandardsAudits.mockResolvedValue([{ id: 1, verdict: 'pass' }]);
    const { result } = renderHook(() => useStandardsAudits(5));

    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(false);
    expect(result.current.audits).toHaveLength(1);
    expect(getStandardsAudits).toHaveBeenCalledWith(5, expect.objectContaining({ signal: expect.anything() }));
  });

  it('sets error true when the fetch rejects', async () => {
    getStandardsAudits.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useStandardsAudits(5));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(true);
    expect(result.current.audits).toHaveLength(0);
  });
});
