// Path: src/components/common/__tests__/Overlay.test.jsx
// File: Overlay.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the generic Overlay modal (DWB-535): renders nothing when closed, portals a dialog with children when open, closes via the close link, the scrim click (but not a click inside the panel), and Esc; traps Tab / Shift+Tab focus inside the panel; restores focus to the opener on close; carries no domain props (arbitrary children render).
// Caller: vitest test runner
// Callees: ../Overlay
// Data In: Controlled open/onClose props
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, afterEach } from 'vitest';
import { useState } from 'react';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';
import Overlay from '../Overlay';

function Host({ initialOpen = false, children }) {
  const [open, setOpen] = useState(initialOpen);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>opener</button>
      <Overlay open={open} onClose={() => setOpen(false)} label="test dialog">
        {children}
      </Overlay>
    </div>
  );
}

describe('Overlay (DWB-535)', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders nothing when closed and a dialog with arbitrary children when open', () => {
    const { rerender } = render(<Overlay open={false} onClose={() => {}}><p>hello</p></Overlay>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    rerender(<Overlay open onClose={() => {}} label="x"><p>hello</p></Overlay>);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-label', 'x');
    expect(screen.getByText('hello')).toBeInTheDocument();
    // portaled to body, outside the react root container
    expect(dialog.closest('body')).toBe(document.body);
  });

  it('closes on the close link', () => {
    const onClose = vi.fn();
    render(<Overlay open onClose={onClose}><p>c</p></Overlay>);
    fireEvent.click(screen.getByText('close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on scrim click but not on a click inside the panel', () => {
    const onClose = vi.fn();
    render(<Overlay open onClose={onClose}><p>inner</p></Overlay>);
    fireEvent.click(screen.getByText('inner'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('overlay-scrim'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<Overlay open onClose={onClose}><p>e</p></Overlay>);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('moves focus into the panel on open and traps Tab / Shift+Tab inside it', () => {
    render(
      <Overlay open onClose={() => {}}>
        <button type="button">one</button>
        <button type="button">two</button>
      </Overlay>
    );
    // first focusable is the close link in the bar
    expect(document.activeElement).toBe(screen.getByText('close'));
    const two = screen.getByText('two');
    two.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByText('close'));
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(two);
    // focus that escaped outside is pulled back in on the next Tab
    document.body.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  it('restores focus to the opener when closed', async () => {
    render(<Host><p>body</p></Host>);
    const opener = screen.getByText('opener');
    opener.focus();
    await act(async () => { fireEvent.click(opener); });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(document.activeElement).not.toBe(opener);
    await act(async () => { fireEvent.keyDown(document, { key: 'Escape' }); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(opener);
  });
});
