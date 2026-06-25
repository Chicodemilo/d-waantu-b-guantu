// Path: src/components/help/__tests__/helpComponents.test.jsx
// File: helpComponents.test.jsx
// Created: 2026-06-25
// Purpose: Isolation tests for the reusable help components (DWB-468): FuzzySearch
//          (controlled value/onChange + clear), CollapsibleSection (controlled open
//          state, body hidden when closed, parent toggle), SummaryHeader (renders
//          only provided Why/How/Where rows + bullet list).
// Caller: vitest test runner
// Callees: ../FuzzySearch, ../CollapsibleSection, ../SummaryHeader
// Data In: synthetic props
// Data Out: test assertions
// Last Modified: 2026-06-25

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import FuzzySearch from '../FuzzySearch';
import CollapsibleSection from '../CollapsibleSection';
import SummaryHeader from '../SummaryHeader';

afterEach(() => cleanup());

describe('FuzzySearch (DWB-468)', () => {
  it('renders as a controlled input and fires onChange', () => {
    const onChange = vi.fn();
    render(<FuzzySearch value="abc" onChange={onChange} label="search" />);
    const input = screen.getByLabelText('search');
    expect(input.value).toBe('abc');
    fireEvent.change(input, { target: { value: 'abcd' } });
    expect(onChange).toHaveBeenCalledWith('abcd');
  });

  it('shows a clear button that resets the value', () => {
    const onChange = vi.fn();
    render(<FuzzySearch value="x" onChange={onChange} />);
    fireEvent.click(screen.getByText('clear'));
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('shows a match count only when querying', () => {
    const { rerender } = render(
      <FuzzySearch value="" onChange={() => {}} resultCount={3} totalCount={5} />
    );
    expect(screen.queryByText(/match/)).toBeNull();
    rerender(
      <FuzzySearch value="ti" onChange={() => {}} resultCount={3} totalCount={5} />
    );
    expect(screen.getByText(/3 \/ 5 matches/)).toBeInTheDocument();
  });
});

describe('CollapsibleSection (DWB-468)', () => {
  it('hides the body when closed and shows it when open (controlled)', () => {
    const { rerender } = render(
      <CollapsibleSection title="Tickets" open={false} onToggle={() => {}}>
        <p>body content</p>
      </CollapsibleSection>
    );
    expect(screen.queryByText('body content')).toBeNull();
    rerender(
      <CollapsibleSection title="Tickets" open onToggle={() => {}}>
        <p>body content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText('body content')).toBeInTheDocument();
  });

  it('asks the parent to toggle (does not self-manage state)', () => {
    const onToggle = vi.fn();
    render(
      <CollapsibleSection title="Team" open={false} onToggle={onToggle}>
        <p>x</p>
      </CollapsibleSection>
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});

describe('SummaryHeader (DWB-468)', () => {
  it('renders only the provided rows and the bullet list', () => {
    render(
      <SummaryHeader
        why="see the board"
        where="tickets page"
        bullets={['filter by status', 'sub-tasks nest']}
      />
    );
    expect(screen.getByText('Why')).toBeInTheDocument();
    expect(screen.getByText('Where')).toBeInTheDocument();
    expect(screen.queryByText('How')).toBeNull();
    expect(screen.getByText('filter by status')).toBeInTheDocument();
    expect(screen.getByText('sub-tasks nest')).toBeInTheDocument();
  });
});
