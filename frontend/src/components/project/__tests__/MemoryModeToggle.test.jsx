// Path: src/components/project/__tests__/MemoryModeToggle.test.jsx
// File: MemoryModeToggle.test.jsx
// Created: 2026-09-29
// Purpose: DWB-588 + DWB-597 tests for the memory_mode toggle. AC3 is the load-bearing one: the confirm is inline text inside the trigger's own node and the component renders no dialog or overlay. Also covers the unconfirmed-then-confirmed PATCH pair and that the warning painted on screen is the server's words rather than a copy kept in the frontend.
// Caller: vitest test runner
// Callees: ../MemoryModeToggle, ../../../api/projects (mocked)
// Data In: Mocked updateProject rejections and resolutions
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-597: the toggle starts a transition, it no longer flips the mode)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor, cleanup, fireEvent } from '@testing-library/react';

vi.mock('../../../api/projects', () => ({
  updateProject: vi.fn(),
}));

import MemoryModeToggle from '../MemoryModeToggle';
import { updateProject } from '../../../api/projects';

// The warning as the API hands it back. This is a STAND-IN for the server's
// words, not a second source of truth: the copy itself is pinned in the backend
// suite (test_memory_mode_toggle_dwb588.py), which is where a reword goes red.
// What these tests prove is that whatever the refusal says reaches the screen.
const SERVER_WARNING = [
  'Switching memory modes rewrites every memory this project has.',
  '',
  'human_memory stores memory in a completely different structure, under different rules, with a different lifecycle.',
  '',
  'Decide this at the start of a project.',
  '',
  "We'll let you do it... but think it thru this time, sport.",
].join('\n');

function refusal() {
  const err = new Error(SERVER_WARNING);
  err.name = 'ApiError';
  err.status = 400;
  return err;
}

const STOCK_PROJECT = {
  id: 7,
  memory_mode: 'stock',
  memory_schema_version: 1,
};

function renderToggle(project = STOCK_PROJECT) {
  return render(<MemoryModeToggle project={project} />);
}

beforeEach(() => {
  updateProject.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('MemoryModeToggle', () => {
  it('shows the current mode and offers to adopt from stock', () => {
    renderToggle();
    expect(screen.getByText(/Mode \[stock\]/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /adopt human_memory/ })
    ).toBeInTheDocument();
  });

  it('offers a revert when the project is already in human_memory', () => {
    renderToggle({ ...STOCK_PROJECT, memory_mode: 'human_memory' });
    expect(
      screen.getByRole('button', { name: /revert to stock/ })
    ).toBeInTheDocument();
  });

  it('asks the API unconfirmed first and paints the refusal warning', async () => {
    updateProject.mockRejectedValueOnce(refusal());
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));

    expect(updateProject).toHaveBeenCalledWith(7, { memory_mode: 'adopting' });
    await waitFor(() => {
      expect(
        screen.getByText(/rewrites every memory this project has/)
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/think it thru this time, sport/)
    ).toBeInTheDocument();
  });

  // AC3. This is the one that matters: inline text, never a modal.
  it('puts the confirm text inside the trigger node and renders no dialog', async () => {
    updateProject.mockRejectedValueOnce(refusal());
    const { container } = renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));

    const trigger = await screen.findByTestId('memory-mode-trigger');
    expect(within(trigger).getByText('confirm?')).toBeInTheDocument();
    expect(within(trigger).getByRole('button', { name: /yes/ })).toBeInTheDocument();
    expect(within(trigger).getByRole('button', { name: /cancel/ })).toBeInTheDocument();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('[role="alertdialog"]')).toBeNull();
    expect(container.querySelector('.overlay')).toBeNull();
    expect(container.querySelector('.overlay__backdrop')).toBeNull();
    expect(container.querySelector('dialog')).toBeNull();
  });

  it('re-sends the PATCH with the confirmation flag on yes', async () => {
    updateProject
      .mockRejectedValueOnce(refusal())
      .mockResolvedValueOnce({ ...STOCK_PROJECT, memory_mode: 'human_memory' });
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));

    await waitFor(() => {
      expect(updateProject).toHaveBeenLastCalledWith(7, {
        memory_mode: 'adopting',
        memory_mode_confirmed: true,
      });
    });
  });

  it('sends nothing more and clears the warning on cancel', async () => {
    updateProject.mockRejectedValueOnce(refusal());
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /cancel/ }));

    await waitFor(() => {
      expect(
        screen.queryByText(/rewrites every memory this project has/)
      ).not.toBeInTheDocument();
    });
    expect(updateProject).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole('button', { name: /adopt human_memory/ })
    ).toBeInTheDocument();
  });

  it('says so visibly when the API cannot be reached', async () => {
    const err = new Error('Request failed: 503');
    err.status = 503;
    updateProject.mockRejectedValueOnce(err);
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));

    await waitFor(() => {
      expect(screen.getByText(/Request failed: 503/)).toBeInTheDocument();
    });
    expect(screen.queryByText('confirm?')).not.toBeInTheDocument();
  });

  // If an unconfirmed switch ever succeeds, the guard is gone. A quiet success
  // here would look exactly like the feature working.
  it('reports a loud failure when an unconfirmed switch goes through', async () => {
    updateProject.mockResolvedValueOnce({
      ...STOCK_PROJECT,
      memory_mode: 'human_memory',
    });
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));

    await waitFor(() => {
      expect(
        screen.getByText(/without asking for confirmation/)
      ).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // DWB-597: the toggle STARTS A TRANSITION rather than flipping the mode.
  //
  // DWB-593 made stock -> human_memory an illegal edge, because the direct
  // flip sealed the flat file against an empty store and every agent on the
  // project spawned amnesiac. The legal edges, verified against the backend
  // rather than assumed: stock -> adopting, adopting -> human_memory,
  // human_memory -> reverting, reverting -> stock, plus aborts back.
  //
  // ONLY THE TARGET CHANGES. The inline confirm and the server-supplied
  // warning are untouched and are still covered by the DWB-588 cases above.
  // -------------------------------------------------------------------------

  it('never sends the illegal direct flip to human_memory', async () => {
    // AC5. This is the case that names the defect: the old component sent
    // exactly this body, and DWB-593 now refuses it.
    updateProject.mockRejectedValueOnce(refusal());
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));

    await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(2));
    for (const [, body] of updateProject.mock.calls) {
      expect(body.memory_mode).not.toBe('human_memory');
    }
  });

  it('starts a revert rather than flipping straight back to stock', async () => {
    updateProject.mockRejectedValueOnce(refusal());
    renderToggle({ ...STOCK_PROJECT, memory_mode: 'human_memory' });

    fireEvent.click(screen.getByRole('button', { name: /revert to stock/ }));

    expect(updateProject).toHaveBeenCalledWith(7, { memory_mode: 'reverting' });
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));
    await waitFor(() => {
      expect(updateProject).toHaveBeenLastCalledWith(7, {
        memory_mode: 'reverting',
        memory_mode_confirmed: true,
      });
    });
  });

  it.each(['adopting', 'reverting'])(
    'offers no start control while the project is %s',
    (mode) => {
      // There is no legal BEGIN edge out of a transition state, so offering
      // one would be a button that can only ever produce a refusal.
      renderToggle({ ...STOCK_PROJECT, memory_mode: mode });
      expect(
        screen.queryByRole('button', { name: /adopt human_memory/ })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /revert to stock/ })
      ).not.toBeInTheDocument();
    }
  );

  // -------------------------------------------------------------------------
  // Abort. The edge map has always permitted it and nothing in the UI reached
  // it, so the escape hatch existed in code and nowhere a human could touch.
  // Both abort edges verified against the running API before these were
  // written: adopting -> stock and reverting -> human_memory, each 200 with NO
  // confirmation flag.
  // -------------------------------------------------------------------------

  it.each([
    ['adopting', 'stock'],
    ['reverting', 'human_memory'],
  ])('lets an operator abort from %s, back to %s', async (mode, back) => {
    updateProject.mockResolvedValueOnce({ ...STOCK_PROJECT, memory_mode: back });
    renderToggle({ ...STOCK_PROJECT, memory_mode: mode });

    fireEvent.click(screen.getByRole('button', { name: /abort/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));

    await waitFor(() => {
      expect(updateProject).toHaveBeenCalledWith(7, { memory_mode: back });
    });
  });

  it('reports a start that completed immediately with nothing to move', async () => {
    // Enumeration runs inside the begin request, so a project whose agents all
    // have empty memory produces zero candidates and lands straight in the
    // destination. We asked for adopting and got human_memory back: success.
    updateProject
      .mockRejectedValueOnce(refusal())
      .mockResolvedValueOnce({ ...STOCK_PROJECT, memory_mode: 'human_memory' });
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));

    await waitFor(() => {
      expect(screen.getByText(/Nothing to move/)).toBeInTheDocument();
    });
    expect(screen.getByText(/already in human_memory/)).toBeInTheDocument();
  });

  it('says nothing extra when the start does what was asked', async () => {
    // The adjacent risk: a note that fires on the normal path would be noise
    // on every single transition anyone ever starts.
    updateProject
      .mockRejectedValueOnce(refusal())
      .mockResolvedValueOnce({ ...STOCK_PROJECT, memory_mode: 'adopting' });
    renderToggle();

    fireEvent.click(screen.getByRole('button', { name: /adopt human_memory/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));

    await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/Nothing to move/)).not.toBeInTheDocument();
  });

  it('never sends a confirmation flag on an abort', async () => {
    // The server does not require one and therefore returns no warning to
    // render. Sending it anyway would be cargo-culting the begin path.
    updateProject.mockResolvedValueOnce({ ...STOCK_PROJECT, memory_mode: 'stock' });
    renderToggle({ ...STOCK_PROJECT, memory_mode: 'adopting' });

    fireEvent.click(screen.getByRole('button', { name: /abort/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    fireEvent.click(within(trigger).getByRole('button', { name: /yes/ }));

    await waitFor(() => expect(updateProject).toHaveBeenCalled());
    for (const [, body] of updateProject.mock.calls) {
      expect(body).not.toHaveProperty('memory_mode_confirmed');
    }
  });

  it('asks before aborting, inline in the trigger, and sends nothing on cancel', async () => {
    // The API needs no confirmation, so this one is ours: an abort discards
    // migration work already done, and a misclick should not.
    renderToggle({ ...STOCK_PROJECT, memory_mode: 'adopting' });

    fireEvent.click(screen.getByRole('button', { name: /abort/ }));
    const trigger = await screen.findByTestId('memory-mode-trigger');
    expect(within(trigger).getByText(/discard/i)).toBeInTheDocument();
    expect(updateProject).not.toHaveBeenCalled();

    fireEvent.click(within(trigger).getByRole('button', { name: /cancel/ }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /abort/ })).toBeInTheDocument();
    });
    expect(updateProject).not.toHaveBeenCalled();
  });

  it('renders no dialog while confirming an abort', async () => {
    const { container } = renderToggle({ ...STOCK_PROJECT, memory_mode: 'adopting' });
    fireEvent.click(screen.getByRole('button', { name: /abort/ }));
    await screen.findByTestId('memory-mode-trigger');
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('dialog')).toBeNull();
    expect(container.querySelector('.overlay')).toBeNull();
  });

  it('offers no abort on a project that is not in a transition', () => {
    renderToggle();
    expect(screen.queryByRole('button', { name: /abort/ })).not.toBeInTheDocument();
  });

  it('names the transition it is in rather than going blank', () => {
    renderToggle({ ...STOCK_PROJECT, memory_mode: 'adopting' });
    expect(screen.getByText(/Mode \[adopting\]/)).toBeInTheDocument();
  });

  it('states that beta is permanent and that nothing is wired to agent behaviour yet', () => {
    renderToggle();
    expect(
      screen.getByText(/stays in beta permanently, by design/)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/does not mean unfinished work on its way to graduating/)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/does not change how any agent behaves/)
    ).toBeInTheDocument();
  });
});
