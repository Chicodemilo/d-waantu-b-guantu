// Path: src/components/common/__tests__/AlertBanner.test.jsx
// File: AlertBanner.test.jsx
// Created: 2026-06-24
// Purpose: Tests for the alert category badge on AlertBanner (DWB-464). Covers rendering the category badge with the category-specific class and omitting it when the alert has no category.
// Caller: vitest test runner
// Callees: ../AlertBanner, ../../../store/useStore (mocked)
// Data In: Mocked store getters + alert prop
// Data Out: Test assertions
// Last Modified: 2026-06-24

import { describe, it, expect, vi, afterEach } from 'vitest';
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
