// Path: src/components/project/__tests__/MemoryTransitionOverlay.test.jsx
// File: MemoryTransitionOverlay.test.jsx
// Created: 2026-09-30
// Purpose: DWB-597 AC1, AC2 and AC3 for the transition status strip: it appears only during a transition, it never blocks the page or renders a dialog, and its counts come from the DWB-596 endpoint rather than being computed here.
// Caller: vitest test runner
// Callees: ../MemoryTransitionOverlay, ../../../api/projects (mocked)
// Data In: Mocked getMemoryTransition responses
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-597)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';

vi.mock('../../../api/projects', () => ({
  getMemoryTransition: vi.fn(),
}));

import MemoryTransitionOverlay from '../MemoryTransitionOverlay';
import { getMemoryTransition } from '../../../api/projects';

// DWB-596's frozen shape. Kept as one builder so a field rename breaks every
// case at once rather than leaving some silently asserting on undefined.
function run(overrides = {}) {
  return {
    state: 'open',
    status: 'in_progress',
    direction: 'adopt',
    started_at: '2026-09-30T10:00:00',
    enumerated_at: '2026-09-30T10:00:05',
    completed_at: null,
    aborted_at: null,
    entries_total: 51,
    entries_done: 34,
    entries_written: 30,
    entries_journaled: 3,
    entries_skipped: 1,
    agents_total: 5,
    agents_done: 2,
    ...overrides,
  };
}

const project = (mode) => ({ id: 7, memory_mode: mode });

beforeEach(() => {
  getMemoryTransition.mockReset();
});
afterEach(() => {
  cleanup();
});

describe('MemoryTransitionOverlay', () => {
  // AC1
  it.each(['stock', 'human_memory'])(
    'renders nothing, and asks nothing, for a %s project',
    async (mode) => {
      const { container } = render(<MemoryTransitionOverlay project={project(mode)} />);
      expect(container).toBeEmptyDOMElement();
      // Not merely "renders nothing": a project that never started a
      // transition is answered by memory_mode, so the request must not happen.
      expect(getMemoryTransition).not.toHaveBeenCalled();
    }
  );

  it.each(['adopting', 'reverting'])('appears while the project is %s', async (mode) => {
    getMemoryTransition.mockResolvedValue(
      run({ direction: mode === 'adopting' ? 'adopt' : 'revert' })
    );
    render(<MemoryTransitionOverlay project={project(mode)} />);
    await waitFor(() => {
      expect(screen.getByText(/34 of 51 entries/)).toBeInTheDocument();
    });
  });

  // AC3: the counts are the endpoint's, not ours.
  it('renders the counts the endpoint gave it', async () => {
    getMemoryTransition.mockResolvedValue(
      run({ entries_done: 12, entries_total: 99, agents_done: 1, agents_total: 8 })
    );
    render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => {
      expect(
        screen.getByText(/Adopting, 12 of 99 entries, 1 of 8 agents done/)
      ).toBeInTheDocument();
    });
  });

  it('says reverting, not adopting, when the run says revert', async () => {
    getMemoryTransition.mockResolvedValue(run({ direction: 'revert' }));
    render(<MemoryTransitionOverlay project={project('reverting')} />);
    await waitFor(() => {
      expect(screen.getByText(/^Reverting,/)).toBeInTheDocument();
    });
  });

  it('says ready to cut over once every entry is done', async () => {
    getMemoryTransition.mockResolvedValue(
      run({ status: 'complete', entries_done: 51, entries_total: 51, entries_written: 48 })
    );
    render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => {
      expect(screen.getByText(/ready to cut over/)).toBeInTheDocument();
    });
  });

  // Enumeration is atomic with BEGIN, so an un-enumerated open run cannot
  // happen in normal operation. It is a defect, and the interface says so
  // rather than describing a phase that does not exist.
  it('reports an un-enumerated run as broken, not as a phase', async () => {
    getMemoryTransition.mockResolvedValue(
      run({ status: 'not_enumerated', enumerated_at: null, entries_total: 0, entries_done: 0 })
    );
    const { container } = render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => {
      expect(screen.getByText(/entries were never enumerated/)).toBeInTheDocument();
    });
    // The two reassuring renderings, both wrong for this state.
    expect(screen.queryByText(/preparing/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 of 0/)).not.toBeInTheDocument();
    expect(container.querySelector('.memory-transition--failed')).not.toBeNull();
  });

  it('refuses to call a run that wrote nothing a success', async () => {
    // Every entry terminal, none written. Complete is correct and the cutover
    // is allowed, but the ordinary sentence would tell a reader it worked
    // right before they confirm a cutover into an empty store.
    getMemoryTransition.mockResolvedValue(
      run({
        status: 'complete',
        entries_total: 51,
        entries_done: 51,
        entries_written: 0,
        entries_skipped: 51,
        entries_journaled: 0,
      })
    );
    const { container } = render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => {
      expect(screen.getByText(/without being written to the new store/)).toBeInTheDocument();
    });
    expect(screen.getByText(/empty memory store/)).toBeInTheDocument();
    expect(screen.queryByText(/ready to cut over/)).not.toBeInTheDocument();
    expect(container.querySelector('.memory-transition--failed')).not.toBeNull();
  });

  it('still reads as success when entries actually landed', async () => {
    // The adjacent risk: a warning that fires on every completed transition
    // is noise on all of them.
    getMemoryTransition.mockResolvedValue(
      run({ status: 'complete', entries_total: 51, entries_done: 51, entries_written: 51, entries_skipped: 0 })
    );
    render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => {
      expect(screen.getByText(/ready to cut over/)).toBeInTheDocument();
    });
    expect(screen.getByText(/51 of 51 written/)).toBeInTheDocument();
    expect(screen.queryByText(/empty memory store/)).not.toBeInTheDocument();
  });

  it('renders nothing when there is no open run', async () => {
    // DWB-596 answers "no open run" with null fields rather than a 404.
    getMemoryTransition.mockResolvedValue({ state: null, status: 'idle', direction: null });
    const { container } = render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => expect(getMemoryTransition).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('says so visibly when the status cannot be read', async () => {
    // A transition IS running and we cannot say how far along. Rendering
    // nothing here is indistinguishable from no transition at all.
    getMemoryTransition.mockRejectedValue(new Error('Request failed: 503'));
    render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => {
      expect(screen.getByText(/could not be read/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Request failed: 503/)).toBeInTheDocument();
  });

  // AC2
  it('renders no dialog, no modal and no overlay node', async () => {
    getMemoryTransition.mockResolvedValue(run());
    const { container } = render(<MemoryTransitionOverlay project={project('adopting')} />);
    await waitFor(() => expect(screen.getByText(/34 of 51/)).toBeInTheDocument());
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('[role="alertdialog"]')).toBeNull();
    expect(container.querySelector('dialog')).toBeNull();
    expect(container.querySelector('.overlay')).toBeNull();
    expect(container.querySelector('[aria-modal]')).toBeNull();
  });

  it('does not block the page underneath it', async () => {
    // The property the whole lane exists to preserve: the project stays fully
    // usable during a transition. Asserted by CLICKING something beside it
    // rather than by inspecting styles, because a style assertion would pass
    // against a transparent element that still swallows the click.
    getMemoryTransition.mockResolvedValue(run());
    const onClick = vi.fn();
    render(
      <div>
        <MemoryTransitionOverlay project={project('adopting')} />
        <button onClick={onClick}>a control on the page</button>
      </div>
    );
    await waitFor(() => expect(screen.getByText(/34 of 51/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /a control on the page/ }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('re-reads on each poll tick while the transition is running', async () => {
    getMemoryTransition.mockResolvedValue(run());
    const { rerender } = render(
      <MemoryTransitionOverlay project={project('adopting')} lastPolled={1} />
    );
    await waitFor(() => expect(getMemoryTransition).toHaveBeenCalledTimes(1));

    rerender(<MemoryTransitionOverlay project={project('adopting')} lastPolled={2} />);
    await waitFor(() => expect(getMemoryTransition).toHaveBeenCalledTimes(2));
  });
});
