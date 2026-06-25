// Path: src/components/project/__tests__/SessionSummary.test.jsx
// File: SessionSummary.test.jsx
// Created: 2026-06-25
// Purpose: Tests for the session write-up block (DWB-486) against the locked
//          DWB-483 contract: graceful empty state when summary is null; lead line;
//          keyword tag row sorted by weight desc; each summary.sections[] rendered
//          as a CollapsibleSection (default open, bullets visible) that collapses on
//          toggle; tolerance of a section with no bullets.
// Caller: vitest test runner
// Callees: ../SessionSummary
// Data In: synthetic summary/keywords props matching the locked contract
// Data Out: test assertions
// Last Modified: 2026-06-25

import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import SessionSummary from '../SessionSummary';

afterEach(() => cleanup());

const summary = {
  lead: 'Shipped the session write-up feature end to end.',
  sections: [
    { title: 'Tickets', bullets: ['3 completed: DWB-486', '2 created'] },
    { title: 'Cost', bullets: ['210k tokens over 3h 12m'] },
  ],
};

describe('SessionSummary (DWB-486)', () => {
  it('shows a graceful empty state when summary is null and no keywords', () => {
    render(<SessionSummary summary={null} keywords={[]} />);
    expect(screen.getByTestId('session-summary-empty')).toBeInTheDocument();
  });

  it('renders the lead line', () => {
    render(<SessionSummary summary={summary} keywords={[]} />);
    expect(
      screen.getByText('Shipped the session write-up feature end to end.')
    ).toBeInTheDocument();
  });

  it('renders keyword tags sorted by weight descending', () => {
    render(
      <SessionSummary
        summary={summary}
        keywords={[
          { keyword: 'low', weight: 3 },
          { keyword: 'high', weight: 50 },
          { keyword: 'mid', weight: 12 },
        ]}
      />
    );
    const tags = screen.getByTestId('session-summary-keywords').querySelectorAll('.session-summary__tag');
    expect([...tags].map((t) => t.textContent)).toEqual(['high', 'mid', 'low']);
  });

  it('renders each section as a CollapsibleSection, default open with bullets visible', () => {
    render(<SessionSummary summary={summary} keywords={[]} />);
    expect(screen.getByRole('button', { name: /Tickets/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cost/ })).toBeInTheDocument();
    // Default open: bullet content is visible without a click.
    expect(screen.getByText('3 completed: DWB-486')).toBeInTheDocument();
    expect(screen.getByText('210k tokens over 3h 12m')).toBeInTheDocument();
  });

  it('collapses a section when its header is toggled', () => {
    render(<SessionSummary summary={summary} keywords={[]} />);
    expect(screen.getByText('210k tokens over 3h 12m')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Cost/ }));
    expect(screen.queryByText('210k tokens over 3h 12m')).toBeNull();
    // The other section stays open.
    expect(screen.getByText('3 completed: DWB-486')).toBeInTheDocument();
  });

  it('tolerates a section with no bullets', () => {
    render(
      <SessionSummary
        summary={{ lead: 'x', sections: [{ title: 'Empty', bullets: [] }] }}
        keywords={[]}
      />
    );
    expect(screen.getByRole('button', { name: /Empty/ })).toBeInTheDocument();
  });

  it('renders content when only keywords exist (no summary)', () => {
    render(<SessionSummary summary={null} keywords={[{ keyword: 'solo', weight: 1 }]} />);
    expect(screen.queryByTestId('session-summary-empty')).toBeNull();
    expect(screen.getByText('solo')).toBeInTheDocument();
  });
});
