// Path: src/components/layout/__tests__/Sidebar.test.jsx
// File: Sidebar.test.jsx
// Created: 2026-06-10
// Purpose: Tests for Sidebar — when a project's sub-nav is expanded, the "sessions" link is present (matches sibling sub-link convention; the visual hyphen prefix comes from CSS, not source) and points at /projects/:pid/sessions
// Caller: vitest test runner
// Callees: ../Sidebar, react-router-dom (MemoryRouter), store/useStore (mocked)
// Data In: Mocked projects array from store
// Data Out: Test assertions
// Last Modified: 2026-06-10

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const projects = [{ id: 1, prefix: 'DWB', name: 'D\'Waantu B\'Guantu', status: 'active' }];
vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector({ projects }),
}));

import Sidebar from '../Sidebar';

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar open={true} onNavClick={() => {}} />
    </MemoryRouter>
  );
}

describe('Sidebar', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders the "sessions" sub-link for an active project, linking to /projects/:pid/sessions', () => {
    renderAt('/projects/1');
    const link = screen.getByText('sessions');
    expect(link).toBeInTheDocument();
    expect(link.getAttribute('href')).toBe('/projects/1/sessions');
  });

  it('sessions link sits alongside sibling sub-links (same plain-text convention)', () => {
    renderAt('/projects/1');
    for (const label of ['tickets', 'team', 'sessions', 'tests', 'docs']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
