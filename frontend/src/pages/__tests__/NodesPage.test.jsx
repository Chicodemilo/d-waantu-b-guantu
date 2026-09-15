// Path: src/pages/__tests__/NodesPage.test.jsx
// File: NodesPage.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the project Nodes cloud page (DWB-534): loading state, render of tag + pointer count with the head count line, log-bucket scaling classes (top nodes share the cap bucket), empty state pointing at POST /nodeify, the 500-node cap with show more / show all, and click emitting a selection (aria-pressed).
// Caller: vitest test runner
// Callees: ../NodesPage, ../../api/nodes (mocked)
// Data In: Mocked getProjectNodes responses in the live NodeRead shape
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../../api/nodes', () => ({
  getProjectNodes: vi.fn(),
  matchProjectNodes: vi.fn(),
}));

import NodesPage from '../NodesPage';
import { getProjectNodes } from '../../api/nodes';
import { NODE_CLOUD_PAGE_SIZE } from '../../components/nodes/NodeCloud';

function pointer(i, kind = 'code') {
  return { id: i, kind, ref: `backend/app/f${i}.py`, sha: 'abc', line_start: i, line_end: i };
}

function node(id, tag, weight, pointerCount) {
  return {
    id,
    project_id: 1,
    tag,
    weight,
    pointers: Array.from({ length: pointerCount }, (_, i) => pointer(id * 1000 + i)),
  };
}

// Live-shaped fixture: API returns weight desc.
const NODES = [
  node(517, 'contract', 121, 3),
  node(1631, 'roster', 121, 2),
  node(1613, 'review', 119, 4),
  node(1939, 'ticket-key', 113, 1),
  node(42, 'middling', 25, 2),
  node(7, 'zelda', 10, 1),
];

function renderAt(path = '/projects/1/nodes') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/nodes" element={<NodesPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('NodesPage (DWB-534)', () => {
  beforeEach(() => {
    getProjectNodes.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('shows a loading state until the list resolves', async () => {
    let resolve;
    getProjectNodes.mockReturnValue(new Promise((r) => { resolve = r; }));
    await act(async () => { renderAt(); });
    expect(screen.getByText('loading nodes...')).toBeInTheDocument();
    await act(async () => { resolve(NODES); });
    await waitFor(() => expect(screen.queryByText('loading nodes...')).not.toBeInTheDocument());
    expect(getProjectNodes).toHaveBeenCalledWith('1', {}, expect.objectContaining({ signal: expect.anything() }));
  });

  it('renders every node as tag + pointer count with the head count line', async () => {
    getProjectNodes.mockResolvedValue(NODES);
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('contract')).toBeInTheDocument());

    expect(screen.getByText('6 nodes, 13 pointers')).toBeInTheDocument();
    const contract = screen.getByText('contract').closest('button');
    expect(contract.querySelector('.node-cloud__count').textContent).toBe('3');
    expect(screen.getByText('zelda').closest('button').querySelector('.node-cloud__count').textContent).toBe('1');
    // stable order = API order (weight desc)
    const tags = [...document.querySelectorAll('.node-cloud__tag')].map((el) => el.textContent);
    expect(tags).toEqual(['contract', 'roster', 'review', 'ticket-key', 'middling', 'zelda']);
    expect(screen.getByText('showing 6 of 6')).toBeInTheDocument();
  });

  it('scales by log bucket: the heavy top nodes share the cap bucket, the lightest is bucket 0', async () => {
    getProjectNodes.mockResolvedValue(NODES);
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('contract')).toBeInTheDocument());

    const bucketOf = (tag) => Number(screen.getByText(tag).closest('button').dataset.bucket);
    expect(bucketOf('contract')).toBe(7);
    expect(bucketOf('roster')).toBe(7);
    expect(bucketOf('review')).toBe(7);
    expect(bucketOf('ticket-key')).toBe(7);
    expect(bucketOf('zelda')).toBe(0);
    const mid = bucketOf('middling');
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(7);
    expect(screen.getByText('contract').closest('button')).toHaveClass('node-cloud__node--b7');
    expect(screen.getByText('zelda').closest('button')).toHaveClass('node-cloud__node--b0');
  });

  it('empty state points at POST /nodeify and offers reload', async () => {
    getProjectNodes.mockResolvedValueOnce([]).mockResolvedValueOnce(NODES);
    await act(async () => { renderAt('/projects/7/nodes'); });
    await waitFor(() => expect(screen.getByText('no nodes indexed for this project yet.')).toBeInTheDocument());
    expect(screen.getByText('POST /api/projects/7/nodeify')).toBeInTheDocument();
    expect(screen.queryByTestId('node-cloud')).not.toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByText('reload')); });
    await waitFor(() => expect(screen.getByText('contract')).toBeInTheDocument());
    expect(getProjectNodes).toHaveBeenCalledTimes(2);
  });

  it('shows the error state with retry when the fetch fails', async () => {
    getProjectNodes.mockRejectedValue(new Error('boom'));
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText(/failed to load nodes: boom/)).toBeInTheDocument());
    expect(screen.getByText('retry')).toBeInTheDocument();
  });

  it('caps the DOM at the page size and grows with show more / show all', async () => {
    const many = Array.from({ length: NODE_CLOUD_PAGE_SIZE * 2 + 50 }, (_, i) =>
      node(i + 1, `tag-${i + 1}`, 121 - (i % 100), 1)
    );
    getProjectNodes.mockResolvedValue(many);
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('tag-1')).toBeInTheDocument());

    expect(document.querySelectorAll('.node-cloud__node')).toHaveLength(NODE_CLOUD_PAGE_SIZE);
    expect(screen.getByText(`showing ${NODE_CLOUD_PAGE_SIZE} of ${many.length}`)).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByText(`show more (${NODE_CLOUD_PAGE_SIZE})`)); });
    expect(document.querySelectorAll('.node-cloud__node')).toHaveLength(NODE_CLOUD_PAGE_SIZE * 2);

    await act(async () => { fireEvent.click(screen.getByText('show more (50)')); });
    expect(document.querySelectorAll('.node-cloud__node')).toHaveLength(many.length);
    expect(screen.queryByText(/show more/)).not.toBeInTheDocument();
    expect(screen.queryByText('show all')).not.toBeInTheDocument();
  });

  it('show all reveals everything in one click when more than a page remains', async () => {
    const many = Array.from({ length: NODE_CLOUD_PAGE_SIZE * 3 }, (_, i) => node(i + 1, `t${i + 1}`, 50, 1));
    getProjectNodes.mockResolvedValue(many);
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('t1')).toBeInTheDocument());
    await act(async () => { fireEvent.click(screen.getByText('show all')); });
    expect(document.querySelectorAll('.node-cloud__node')).toHaveLength(many.length);
  });

  it('clicking a node emits a selection marked with aria-pressed', async () => {
    getProjectNodes.mockResolvedValue(NODES);
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('review')).toBeInTheDocument());

    const review = screen.getByText('review').closest('button');
    expect(review).toHaveAttribute('aria-pressed', 'false');
    await act(async () => { fireEvent.click(review); });
    expect(review).toHaveAttribute('aria-pressed', 'true');
    expect(review).toHaveClass('node-cloud__node--selected');
    expect(screen.getByText('contract').closest('button')).toHaveAttribute('aria-pressed', 'false');
  });
});
