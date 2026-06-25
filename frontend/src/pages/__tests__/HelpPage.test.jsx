// Path: src/pages/__tests__/HelpPage.test.jsx
// File: HelpPage.test.jsx
// Created: 2026-06-25
// Purpose: Tests for the Help Center page (DWB-469, DWB-496) against the REAL
//          helpContent index (glob-discovered sections + quickStart). Covers:
//          quick-start flow steps and standalone callouts render as separate regions;
//          domain sections render under nav-mirroring group labels; sections start
//          collapsed and toggle open; fuzzy search filters live and force-opens
//          matches; a no-match query shows the empty state; quick-start is a
//          collapsible defaulting open (DWB-496); a section cross-link force-opens
//          and scrolls its target (DWB-496); a global-section portal link SPA-navigates
//          to its route while project-scoped sections have none (DWB-501).
// Caller: vitest test runner
// Callees: ../HelpPage, helpContent (real data via import.meta.glob)
// Data In: real static help content
// Data Out: test assertions
// Last Modified: 2026-06-25

import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import HelpPage from '../HelpPage';

afterEach(() => cleanup());

// HelpPage renders React Router <Link>s (DWB-501 portal links), so it must be
// mounted inside a router. LocationProbe exposes the current path for nav assertions.
function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname}</div>;
}

function renderHelp() {
  return render(
    <MemoryRouter initialEntries={['/help']}>
      <HelpPage />
      <LocationProbe />
    </MemoryRouter>
  );
}

describe('HelpPage quick start (DWB-469)', () => {
  it('renders the linear startup flow and standalone callouts as separate regions', () => {
    const { container } = renderHelp();
    // Flow region exists and renders ordered steps (titles are owned by DWB-470,
    // so assert structure, not specific copy).
    expect(screen.getByText('Startup flow')).toBeInTheDocument();
    expect(container.querySelectorAll('.help-flow__step').length).toBeGreaterThan(0);
    // Callouts region is a separate block with the two stable shortcuts.
    expect(screen.getByText('Shortcuts')).toBeInTheDocument();
    expect(screen.getByText('Make a quick project')).toBeInTheDocument();
    expect(screen.getByText('Seed a demo')).toBeInTheDocument();
  });
});

describe('HelpPage domain sections (DWB-469)', () => {
  it('renders nav-mirroring group labels and the dashboard section', () => {
    renderHelp();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Dashboard/ })).toBeInTheDocument();
  });

  it('renders the Per-project group with the Inter-Agent Comms section (DWB-472)', () => {
    renderHelp();
    expect(screen.getByText('Per-project')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Inter-Agent Comms/ })
    ).toBeInTheDocument();
  });

  it('starts a section collapsed and opens it on click', () => {
    renderHelp();
    // Closed: SummaryHeader Why row not in the DOM yet.
    expect(screen.queryByText('Why')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Dashboard/ }));
    expect(screen.getByText('Why')).toBeInTheDocument();
  });
});

describe('HelpPage fuzzy search (DWB-469)', () => {
  it('filters to matches and force-opens them', () => {
    renderHelp();
    const input = screen.getByLabelText('search help');
    fireEvent.change(input, { target: { value: 'dashboard' } });
    // Matches are force-opened: at least one summary body is visible with no click.
    expect(screen.getAllByText('Why').length).toBeGreaterThan(0);
    // The matched dashboard section header is present...
    expect(screen.getByRole('button', { name: /Dashboard/ })).toBeInTheDocument();
    // ...and an unrelated section is filtered out of the results.
    expect(screen.queryByRole('button', { name: /^Jira/ })).toBeNull();
  });

  it('shows an empty state when nothing matches', () => {
    renderHelp();
    const input = screen.getByLabelText('search help');
    fireEvent.change(input, { target: { value: 'zzzzzzzz' } });
    expect(screen.getByText(/No topics match/)).toBeInTheDocument();
  });
});

describe('HelpPage quick start collapsible (DWB-496)', () => {
  it('renders the quick-start as a collapsible that defaults open', () => {
    renderHelp();
    expect(screen.getByRole('button', { name: /Quick start/ })).toBeInTheDocument();
    // Default open: the body content is visible without a click.
    expect(screen.getByText('Startup flow')).toBeInTheDocument();
  });

  it('collapses the quick-start when its header is toggled', () => {
    renderHelp();
    expect(screen.getByText('Startup flow')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Quick start/ }));
    expect(screen.queryByText('Startup flow')).toBeNull();
  });
});

describe('HelpPage cross-links (DWB-496)', () => {
  it('a section cross-link force-opens and scrolls its target section', () => {
    const scrollSpy = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = scrollSpy;

    const { container } = renderHelp();
    // Open the dashboard section so its "See also" links render.
    fireEvent.click(screen.getByRole('button', { name: /Dashboard/ }));

    const dashSection = container.querySelector('#help-section-dashboard');
    expect(dashSection).not.toBeNull();
    // Target section starts closed.
    const ticketsSection = container.querySelector('#help-section-tickets');
    expect(ticketsSection.classList.contains('collapsible--open')).toBe(false);

    // Click the dashboard -> Tickets cross-link (scoped to avoid the Tickets
    // section header button of the same name).
    const link = within(dashSection).getByRole('button', { name: 'Tickets' });
    fireEvent.click(link);

    // Target is now force-open and was scrolled into view.
    expect(
      container.querySelector('#help-section-tickets').classList.contains('collapsible--open')
    ).toBe(true);
    expect(scrollSpy).toHaveBeenCalled();
  });
});

describe('HelpPage portal links (DWB-501)', () => {
  it('renders a global section portal link and SPA-navigates to its route', () => {
    const { container } = renderHelp();
    expect(screen.getByTestId('loc').textContent).toBe('/help');

    // Open the dashboard section so its links render.
    fireEvent.click(screen.getByRole('button', { name: /Dashboard/ }));

    const dashSection = container.querySelector('#help-section-dashboard');
    // Portal link renders as an anchor (role link), not a button.
    const portal = within(dashSection).getByRole('link', { name: /Open the dashboard/ });
    expect(portal.getAttribute('href')).toBe('/');

    // Clicking SPA-navigates (no full reload) to the route.
    fireEvent.click(portal);
    expect(screen.getByTestId('loc').textContent).toBe('/');
  });

  it('does not give project-scoped sections a portal link', () => {
    const { container } = renderHelp();
    fireEvent.click(screen.getByRole('button', { name: /Inter-Agent Comms/ }));
    const commsSection = container.querySelector('#help-section-comms');
    // comms keeps section cross-links (buttons) but no portal anchor.
    expect(within(commsSection).queryByRole('link')).toBeNull();
  });
});
