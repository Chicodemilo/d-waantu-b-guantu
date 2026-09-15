// Path: src/components/common/__tests__/AlertBanner.test.jsx
// File: AlertBanner.test.jsx
// Created: 2026-06-24
// Purpose: Tests for the alert category badge on AlertBanner (DWB-464) and its relative timestamp (DWB-554). Covers rendering the category badge with the category-specific class, omitting it when the alert has no category, and rendering a naive-UTC created_at as the correct age in any runner timezone, including the 7-day switch to an absolute date that the private relativeTime used to own.
// Caller: vitest test runner
// Callees: ../AlertBanner, ../../../store/useStore (mocked), ../../../utils/format (real, via the component)
// Data In: Mocked store getters + alert prop
// Data Out: Test assertions
// Last Modified: 2026-09-15 (DWB-554)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector({
    dismissAlert: () => {},
    getAgent: () => ({ name: 'Sage' }),
    getProject: () => ({ prefix: 'DWB' }),
  }),
}));

import AlertBanner from '../AlertBanner';

afterEach(() => cleanup());

describe('AlertBanner category badge (DWB-464)', () => {
  it('renders a category badge with the category-specific class', () => {
    render(
      <AlertBanner alert={{ id: 1, severity: 'warning', category: 'actionable', title: 'Do the thing', created_at: null }} />
    );
    const badge = document.querySelector('.alert-category-badge');
    expect(badge).toBeTruthy();
    expect(badge.textContent).toBe('actionable');
    expect(badge.classList.contains('alert-category-badge--actionable')).toBe(true);
  });

  it('omits the category badge when the alert has no category', () => {
    render(
      <AlertBanner alert={{ id: 2, severity: 'info', title: 'No category', created_at: null }} />
    );
    expect(document.querySelector('.alert-category-badge')).toBeNull();
    // Title still renders.
    expect(screen.getByText('No category')).toBeInTheDocument();
  });
});

describe('AlertBanner relative timestamp (DWB-554)', () => {
  // Naive-UTC input, fixed expectations: these hold in any runner timezone.
  const NOW_UTC = Date.parse('2026-09-15T12:00:00Z');
  const time = () => document.querySelector('.alert-banner__time').textContent;

  const renderAt = (created_at) => render(
    <AlertBanner alert={{ id: 9, severity: 'info', title: 'T', created_at }} />
  );

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW_UTC);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders minutes, hours and days from a naive-UTC timestamp', () => {
    renderAt('2026-09-15T11:30:00');
    expect(time()).toBe('30m ago');
    cleanup();
    renderAt('2026-09-15T09:00:00');
    expect(time()).toBe('3h ago');
    cleanup();
    renderAt('2026-09-13T12:00:00');
    expect(time()).toBe('2d ago');
  });

  it('keeps the 7-day switch to an absolute local date', () => {
    // 6 days stays relative, 7 days becomes the absolute rendering.
    renderAt('2026-09-09T12:00:00');
    expect(time()).toBe('6d ago');
    cleanup();

    const stale = '2026-09-08T12:00:00';
    renderAt(stale);
    expect(time()).not.toMatch(/ago/);
    // Same instant, same formatting: TZ-independent as an equality, and it pins
    // the instant as UTC rather than local.
    const expected = new Date(Date.parse(`${stale}Z`)).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    });
    expect(time()).toBe(expected);
  });

  it('renders no timestamp element at all when the alert has no created_at', () => {
    renderAt(null);
    expect(document.querySelector('.alert-banner__time')).toBeNull();
  });
});
