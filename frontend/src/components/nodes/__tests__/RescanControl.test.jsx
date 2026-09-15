// Path: src/components/nodes/__tests__/RescanControl.test.jsx
// File: RescanControl.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the shared rescan control (DWB-556): the confirm appears in place on the first click, yes starts exactly one pass, cancel restores the control without starting one, Esc and an outside click cancel, a running pass disables the control and drops any open confirm so it cannot be re-entered, and no dialog is ever used for the confirm.
// Caller: vitest test runner
// Callees: ../RescanControl
// Data In: onConfirm spy, running flag
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';
import RescanControl from '../RescanControl';

afterEach(() => {
  cleanup();
});

const trigger = () => screen.getByRole('button', { name: 'rescan' });

describe('RescanControl (DWB-556)', () => {
  it('shows the inline confirm in place on the first click, with no dialog', () => {
    render(<RescanControl onConfirm={() => {}} />);
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();

    fireEvent.click(trigger());
    const confirm = screen.getByTestId('rescan-confirm');
    expect(confirm).toHaveTextContent('rescan? yes / cancel');
    // the trigger is replaced in place, not added alongside
    expect(screen.queryByRole('button', { name: 'rescan' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('yes starts exactly one pass and restores the control', () => {
    const onConfirm = vi.fn();
    render(<RescanControl onConfirm={onConfirm} />);
    fireEvent.click(trigger());
    fireEvent.click(screen.getByText('yes'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
    expect(trigger()).toBeInTheDocument();
  });

  it('cancel restores the control without starting a pass', () => {
    const onConfirm = vi.fn();
    render(<RescanControl onConfirm={onConfirm} />);
    fireEvent.click(trigger());
    fireEvent.click(screen.getByText('cancel'));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
    expect(trigger()).toBeInTheDocument();
  });

  it('Escape cancels the confirm and stops the event reaching an overlay underneath', () => {
    const onConfirm = vi.fn();
    const overlayEscape = vi.fn();
    // mirrors Overlay: a bubble-phase document listener that would close the panel
    document.addEventListener('keydown', overlayEscape);
    try {
      render(<RescanControl onConfirm={onConfirm} />);
      fireEvent.click(trigger());
      act(() => { fireEvent.keyDown(document, { key: 'Escape' }); });
      expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
      expect(onConfirm).not.toHaveBeenCalled();
      expect(overlayEscape).not.toHaveBeenCalled();
    } finally {
      document.removeEventListener('keydown', overlayEscape);
    }
  });

  it('a click elsewhere cancels, a click inside the confirm does not', () => {
    const onConfirm = vi.fn();
    render(<div><RescanControl onConfirm={onConfirm} /><span data-testid="outside">elsewhere</span></div>);
    fireEvent.click(trigger());

    // inside first: still confirming
    act(() => { fireEvent.mouseDown(screen.getByTestId('rescan-confirm')); });
    expect(screen.getByTestId('rescan-confirm')).toBeInTheDocument();

    act(() => { fireEvent.mouseDown(screen.getByTestId('outside')); });
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('while a pass runs the control is disabled and the confirm cannot be entered', () => {
    const onConfirm = vi.fn();
    const { rerender } = render(<RescanControl onConfirm={onConfirm} running />);
    const btn = screen.getByRole('button', { name: 'rescanning...' });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(btn);
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    rerender(<RescanControl onConfirm={onConfirm} running={false} />);
    expect(trigger()).not.toBeDisabled();
  });

  it('a pass starting while the confirm is open drops the confirm, so it cannot be re-entered', () => {
    const onConfirm = vi.fn();
    const { rerender } = render(<RescanControl onConfirm={onConfirm} running={false} />);
    fireEvent.click(trigger());
    expect(screen.getByTestId('rescan-confirm')).toBeInTheDocument();

    rerender(<RescanControl onConfirm={onConfirm} running />);
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'rescanning...' })).toBeDisabled();

    // and when the pass ends the control is back in its idle state, not confirming
    rerender(<RescanControl onConfirm={onConfirm} running={false} />);
    expect(screen.queryByTestId('rescan-confirm')).not.toBeInTheDocument();
    expect(trigger()).toBeInTheDocument();
  });

  it('honours the call-site label and class so both sites share one behaviour', () => {
    render(<RescanControl onConfirm={() => {}} label="rescan now" className="exclusions__rescan" />);
    const btn = screen.getByRole('button', { name: 'rescan now' });
    expect(btn).toHaveClass('exclusions__rescan');
    fireEvent.click(btn);
    expect(screen.getByTestId('rescan-confirm')).toHaveTextContent('rescan? yes / cancel');
  });
});
