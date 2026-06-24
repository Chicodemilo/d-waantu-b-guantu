// Path: src/components/tickets/__tests__/TicketList.test.jsx
// File: TicketList.test.jsx
// Created: 2026-06-24
// Purpose: Tests for sub-task nesting in the ticket list (DWB-457). Covers children rendering indented directly under their parent, the parent-reference tag, the subtask type badge, and the orphan case where a child whose parent is filtered out still renders with its parent-ref.
// Caller: vitest test runner
// Callees: ../TicketList, ../../../store/useStore (mocked), ../../../api/jira (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked store tickets + jira config
// Data Out: Test assertions
// Last Modified: 2026-06-24

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../api/jira', () => ({
  getJiraConfig: vi.fn(() => Promise.resolve({ configured: false })),
  searchJiraIssues: vi.fn(() => Promise.resolve([])),
}));

let mockState;
vi.mock('../../../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import TicketList from '../TicketList';

function seed(tickets) {
  mockState = {
    getTicketsByProject: () => tickets,
    getProject: () => ({ id: 1, prefix: 'DWB', jira_project_key: null }),
    agents: [],
    sprints: [],
    epics: [],
    jiraConfig: { configured: false },
    setJiraConfig: () => {},
    jiraIssues: {},
    setJiraIssue: () => {},
    // TicketFilters selectors:
    getSprintsByProject: () => [],
    getEpicsByProject: () => [],
  };
}

function ticket(over = {}) {
  return {
    id: 1,
    ticket_key: 'DWB-1',
    title: 'parent ticket',
    status: 'todo',
    ticket_type: 'task',
    parent_ticket_id: null,
    sprint_id: null,
    epic_id: null,
    assigned_agent_id: null,
    tokens_used: 0,
    time_spent_seconds: 0,
    jira_issue_key: null,
    ...over,
  };
}

function renderList() {
  return render(
    <MemoryRouter>
      <TicketList projectId={1} />
    </MemoryRouter>
  );
}

// Data rows in display order (excludes the header row).
function dataRows() {
  return Array.from(document.querySelectorAll('.ticket-row'))
    .filter((el) => !el.classList.contains('ticket-row--header'));
}

beforeEach(() => seed([]));
afterEach(() => cleanup());

describe('TicketList sub-task nesting (DWB-457)', () => {
  it('renders a child indented directly under its parent with a parent reference', () => {
    seed([
      ticket({ id: 1, ticket_key: 'DWB-1', title: 'parent ticket' }),
      ticket({ id: 2, ticket_key: 'DWB-2', title: 'child ticket', ticket_type: 'subtask', parent_ticket_id: 1 }),
    ]);
    renderList();

    const rows = dataRows();
    expect(rows).toHaveLength(2);
    // Parent first, child immediately after.
    expect(rows[0].textContent).toContain('DWB-1');
    expect(rows[1].textContent).toContain('DWB-2');
    // Child row carries the nesting class and a parent reference.
    expect(rows[1].classList.contains('ticket-row--subtask')).toBe(true);
    expect(rows[0].classList.contains('ticket-row--subtask')).toBe(false);
    expect(rows[1].textContent).toContain('child of DWB-1');
  });

  it('renders a subtask type badge for subtask-typed tickets', () => {
    seed([
      ticket({ id: 1, ticket_key: 'DWB-1' }),
      ticket({ id: 2, ticket_key: 'DWB-2', ticket_type: 'subtask', parent_ticket_id: 1 }),
    ]);
    renderList();
    const badge = document.querySelector('.ticket-type-badge--subtask');
    expect(badge).toBeTruthy();
    expect(badge.textContent).toBe('subtask');
  });

  it('keeps the parent reference on an orphan child whose parent is filtered out of the view', () => {
    // The parent exists in the project ticket set but is hidden from the view
    // (backlog status is filtered out by default). The child must then render
    // at top level (not indented) yet still resolve its parent-ref key from the
    // full ticket set, so the relationship is never lost.
    seed([
      ticket({ id: 1, ticket_key: 'DWB-1', title: 'hidden parent', status: 'backlog' }),
      ticket({ id: 2, ticket_key: 'DWB-2', title: 'orphan child', status: 'todo', ticket_type: 'subtask', parent_ticket_id: 1 }),
    ]);
    renderList();

    const rows = dataRows();
    // Only the child is visible (parent is backlog -> filtered out by default).
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('DWB-2');
    // Not indented, since the parent isn't in the visible set...
    expect(rows[0].classList.contains('ticket-row--subtask')).toBe(false);
    // ...but the parent-ref key still resolves from the full ticket set.
    expect(rows[0].textContent).toContain('child of DWB-1');
  });
});
