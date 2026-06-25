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

  // DWBG-009: TL-authored narrative block.
  const narrative = {
    lead: 'Decided to store narrative as a sibling JSON column.',
    sections: [{ title: 'Decisions', bullets: ['summary left untouched as baseline'] }],
  };

  it('renders the narrative block with its lead, sections, and provenance', () => {
    render(
      <SessionSummary
        summary={summary}
        keywords={[]}
        narrative={narrative}
        narrativeAuthor="tl"
        narrativeGeneratedAt="2026-06-25T12:00:00"
      />
    );
    const block = screen.getByTestId('session-summary-narrative');
    expect(block).toBeInTheDocument();
    expect(screen.getByText('Decided to store narrative as a sibling JSON column.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Decisions/ })).toBeInTheDocument();
    expect(screen.getByText('summary left untouched as baseline')).toBeInTheDocument();
    // Provenance line shows author + date (date sliced to YYYY-MM-DD).
    expect(block.textContent).toContain('authored by tl');
    expect(block.textContent).toContain('2026-06-25');
  });

  it('renders no narrative block when narrative is null', () => {
    render(<SessionSummary summary={summary} keywords={[]} narrative={null} />);
    expect(screen.queryByTestId('session-summary-narrative')).toBeNull();
  });

  it('renders content when only a narrative exists (no summary/keywords)', () => {
    render(<SessionSummary summary={null} keywords={[]} narrative={narrative} narrativeAuthor="summarizer" />);
    expect(screen.queryByTestId('session-summary-empty')).toBeNull();
    expect(screen.getByTestId('session-summary-narrative')).toBeInTheDocument();
    expect(screen.getByText(/authored by summarizer/)).toBeInTheDocument();
  });

  // DWBG-015: rich narrative rendering — code chips, links, plain-text fallback.
  describe('rich narrative rendering (DWBG-015)', () => {
    it('renders inline `code` in narrative bullets as code chips', () => {
      const rich = {
        lead: 'x',
        sections: [
          { title: 'Code', bullets: ['Wired `InlineMarkdown` into the narrative path'] },
        ],
      };
      const { container } = render(<SessionSummary summary={null} keywords={[]} narrative={rich} />);
      const chip = container.querySelector('.narrative-chip');
      expect(chip).not.toBeNull();
      expect(chip.tagName).toBe('CODE');
      expect(chip.textContent).toBe('InlineMarkdown');
      // The surrounding prose still renders.
      expect(screen.getByText(/Wired/)).toBeInTheDocument();
      expect(screen.getByText(/into the narrative path/)).toBeInTheDocument();
    });

    it('renders [text](url) markdown links in narrative bullets as anchors', () => {
      const rich = {
        lead: 'x',
        sections: [
          { title: 'Links', bullets: ['See the [PR](https://example.com/pr/1) for details'] },
        ],
      };
      const { container } = render(<SessionSummary summary={null} keywords={[]} narrative={rich} />);
      const link = container.querySelector('a.narrative-link');
      expect(link).not.toBeNull();
      expect(link.getAttribute('href')).toBe('https://example.com/pr/1');
      expect(link.textContent).toBe('PR');
      expect(link.getAttribute('rel')).toContain('noopener');
    });

    it('renders bare file refs as clickable links only when a refResolver supplies an href', () => {
      const rich = {
        lead: 'x',
        sections: [
          { title: 'Files', bullets: ['Touched frontend/src/api/sessions.js this session'] },
        ],
      };
      const resolver = (ref) =>
        ref === 'frontend/src/api/sessions.js' ? 'https://repo/blob/frontend/src/api/sessions.js' : null;
      const { container } = render(
        <SessionSummary summary={null} keywords={[]} narrative={rich} refResolver={resolver} />
      );
      const link = container.querySelector('a.narrative-link--ref');
      expect(link).not.toBeNull();
      expect(link.getAttribute('href')).toBe('https://repo/blob/frontend/src/api/sessions.js');
      expect(link.textContent).toBe('frontend/src/api/sessions.js');
    });

    it('falls back to plain text for narrative bullets with no markdown', () => {
      const rich = {
        lead: 'x',
        sections: [{ title: 'Plain', bullets: ['Just ordinary prose with no markup'] }],
      };
      const { container } = render(<SessionSummary summary={null} keywords={[]} narrative={rich} />);
      expect(screen.getByText('Just ordinary prose with no markup')).toBeInTheDocument();
      // No chips/links manufactured out of plain prose.
      expect(container.querySelector('.narrative-chip')).toBeNull();
      expect(container.querySelector('a.narrative-link')).toBeNull();
    });

    it('does NOT apply rich rendering to the deterministic summary (chips stay literal text)', () => {
      const plainSummary = {
        lead: 'x',
        sections: [{ title: 'Det', bullets: ['Edited `SessionSummary.jsx` here'] }],
      };
      const { container } = render(<SessionSummary summary={plainSummary} keywords={[]} />);
      // Summary path renders backticks verbatim, no code chip element.
      expect(container.querySelector('.narrative-chip')).toBeNull();
      expect(screen.getByText('Edited `SessionSummary.jsx` here')).toBeInTheDocument();
    });
  });
});
