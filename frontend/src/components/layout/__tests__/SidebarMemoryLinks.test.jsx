// Path: src/components/layout/__tests__/SidebarMemoryLinks.test.jsx
// File: SidebarMemoryLinks.test.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: Tests for the journal/top-off sidebar sub-links added under
//          human_memory - present only when a project's memory_mode is
//          'human_memory', absent for stock projects (kept in its own file
//          since Sidebar.test.jsx's mock project has no memory_mode field
//          and changing that shared fixture is out of this ticket's scope).
// Caller: vitest test runner
// Callees: ../Sidebar, react-router-dom (MemoryRouter), store/useStore (mocked)
// Data In: Mocked projects array from store
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-613)

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, queryByText } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

let mockProjects;
vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector({ projects: mockProjects }),
}));

import Sidebar from '../Sidebar';

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar open={true} onNavClick={() => {}} />
    </MemoryRouter>
  );
}

afterEach(() => {
  cleanup();
});

describe('Sidebar journal/top-off links (DWB-613)', () => {
  it('shows journal and top-off links for a project running human_memory', () => {
    mockProjects = [{ id: 2, prefix: 'HM', name: 'Human Memory Project', status: 'active', memory_mode: 'human_memory' }];
    renderAt('/projects/2');

    const journalLink = screen.getByText('journal');
    expect(journalLink.getAttribute('href')).toBe('/projects/2/journal');
    const topoffLink = screen.getByText('top-off');
    expect(topoffLink.getAttribute('href')).toBe('/projects/2/topoff');
  });

  it('hides journal and top-off links for a stock-mode project', () => {
    mockProjects = [{ id: 3, prefix: 'STK', name: 'Stock Project', status: 'active', memory_mode: 'stock' }];
    const { container } = renderAt('/projects/3');

    expect(queryByText(container, 'journal')).not.toBeInTheDocument();
    expect(queryByText(container, 'top-off')).not.toBeInTheDocument();
  });
});
