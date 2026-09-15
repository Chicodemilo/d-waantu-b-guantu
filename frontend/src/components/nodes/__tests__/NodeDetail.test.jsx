// Path: src/components/nodes/__tests__/NodeDetail.test.jsx
// File: NodeDetail.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the node detail overlay content (DWB-535): renders tag, weight, pointer count, pointers grouped by kind with ref + line range, neighbors sorted by shared_refs desc with their shared count; a neighbor click hops (content swaps in place, match refetched by the neighbor tag, trail + back link appear); neighbor list is capped with show more; match failure shows the error but keeps the seed pointers.
// Caller: vitest test runner
// Callees: ../NodeDetail, ../../../api/nodes (mocked)
// Data In: Mocked matchProjectNodes responses in the live NodeMatchResponse shape
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent, within } from '@testing-library/react';

vi.mock('../../../api/nodes', () => ({
  getProjectNodes: vi.fn(),
  matchProjectNodes: vi.fn(),
}));

import NodeDetail, { NEIGHBOR_PAGE_SIZE } from '../NodeDetail';
import { matchProjectNodes } from '../../../api/nodes';

const P = (id, kind, ref, s, e) => ({ id, kind, ref, sha: 'deadbeef', line_start: s, line_end: e });

const CONTRACT = {
  id: 517, project_id: 1, tag: 'contract', weight: 121,
  pointers: [P(1, 'code', 'backend/app/services/node_registry.py', 106, 106), P(2, 'doc', 'ARCHITECTURE.md', 10, 24), P(3, 'code', 'backend/app/routers/hooks.py', 176, 176), P(4, 'memory', '.dwb/memory/DWB/Freddie/memory.md', 3, 3)],
};

function matchResponse(node, neighbors) {
  return { query: node.tag, query_tags: [node.tag], nodes: [{ ...node, neighbors }] };
}

const CONTRACT_NEIGHBORS = [
  { id: 921, tag: 'guard', weight: 116, shared_refs: ['ARCHITECTURE.md', 'backend/app/routers/hooks.py'] },
  { id: 1613, tag: 'review', weight: 119, shared_refs: ['ARCHITECTURE.md'] },
  { id: 7, tag: 'zelda', weight: 10, shared_refs: ['ARCHITECTURE.md', 'CLAUDE.md', 'README.md'] },
];

const GUARD = { id: 921, project_id: 1, tag: 'guard', weight: 116, pointers: [P(9, 'code', 'backend/app/routers/hooks.py', 176, 180)] };
const GUARD_NEIGHBORS = [{ id: 517, tag: 'contract', weight: 121, shared_refs: ['backend/app/routers/hooks.py'] }];

describe('NodeDetail (DWB-535)', () => {
  // Braces matter: an arrow returning mockReset()'s value hands the mock itself back to the runner,
  // which calls any returned function as a teardown and would invoke the mock with no arguments.
  beforeEach(() => {
    matchProjectNodes.mockReset();
  });
  afterEach(() => {
    cleanup();
  });

  it('renders tag, weight, pointer count, pointers grouped by kind with line ranges, and neighbors', async () => {
    matchProjectNodes.mockResolvedValue(matchResponse(CONTRACT, CONTRACT_NEIGHBORS));
    await act(async () => { render(<NodeDetail projectId="1" node={CONTRACT} />); });
    await waitFor(() => expect(screen.getByText('3 shared')).toBeInTheDocument());

    expect(matchProjectNodes).toHaveBeenCalledWith('1', 'contract', expect.objectContaining({ signal: expect.anything() }));
    expect(screen.getByText('contract')).toHaveClass('node-detail__tag');
    expect(screen.getByText('weight 121')).toBeInTheDocument();
    expect(screen.getByText('4 pointers')).toBeInTheDocument();

    const kinds = [...document.querySelectorAll('.node-detail__kind')].map((el) => el.textContent.trim().split(/\s+/)[0]);
    expect(kinds).toEqual(['code', 'doc', 'memory']);
    expect(screen.getByText('backend/app/services/node_registry.py').nextSibling.textContent).toBe(':106');
    expect(screen.getByText('ARCHITECTURE.md').nextSibling.textContent).toBe(':10-24');

    // neighbors sorted by shared_refs desc: zelda(3) guard(2) review(1)
    const tags = [...document.querySelectorAll('.node-detail__neighbor-tag')].map((el) => el.textContent);
    expect(tags).toEqual(['zelda', 'guard', 'review']);
    expect(screen.getByText('guard').closest('button')).toHaveAttribute('title', 'ARCHITECTURE.md\nbackend/app/routers/hooks.py');
    expect(screen.queryByText('back')).not.toBeInTheDocument();
  });

  it('hops to a neighbor: content swaps in place, match refetched by the neighbor tag, trail + back work', async () => {
    matchProjectNodes.mockImplementation((pid, text) => {
      if (text === 'contract') return Promise.resolve(matchResponse(CONTRACT, CONTRACT_NEIGHBORS));
      if (text === 'guard') return Promise.resolve(matchResponse(GUARD, GUARD_NEIGHBORS));
      return Promise.resolve({ query: text, query_tags: [text], nodes: [] });
    });
    await act(async () => { render(<NodeDetail projectId="1" node={CONTRACT} />); });
    await waitFor(() => expect(screen.getByText('guard')).toBeInTheDocument());

    await act(async () => { fireEvent.click(screen.getByText('guard').closest('button')); });
    await waitFor(() => expect(screen.getByText('weight 116')).toBeInTheDocument());

    expect(matchProjectNodes).toHaveBeenLastCalledWith('1', 'guard', expect.anything());
    expect(document.querySelector('.node-detail__tag').textContent).toBe('guard');
    expect(screen.getByText('1 pointer')).toBeInTheDocument();
    expect(screen.getByText('backend/app/routers/hooks.py').nextSibling.textContent).toBe(':176-180');
    // only one detail block: swapped, not stacked
    expect(screen.getAllByTestId('node-detail')).toHaveLength(1);
    // trail contract > guard with back
    const trail = document.querySelector('.node-detail__trail');
    expect(trail.textContent).toContain('contract');
    expect(trail.textContent).toContain('guard');
    // new neighbors list is guard's
    expect([...document.querySelectorAll('.node-detail__neighbor-tag')].map((el) => el.textContent)).toEqual(['contract']);

    await act(async () => { fireEvent.click(screen.getByText('back')); });
    await waitFor(() => expect(screen.getByText('weight 121')).toBeInTheDocument());
    expect(document.querySelector('.node-detail__tag').textContent).toBe('contract');
    expect(screen.queryByText('back')).not.toBeInTheDocument();
  });

  it('caps the neighbor list and grows with show more', async () => {
    const many = Array.from({ length: NEIGHBOR_PAGE_SIZE + 15 }, (_, i) => ({ id: 10000 + i, tag: `nb-${i}`, weight: 50, shared_refs: ['x'] }));
    matchProjectNodes.mockResolvedValue(matchResponse(CONTRACT, many));
    await act(async () => { render(<NodeDetail projectId="1" node={CONTRACT} />); });
    await waitFor(() => expect(document.querySelectorAll('.node-detail__neighbor')).toHaveLength(NEIGHBOR_PAGE_SIZE));
    expect(screen.getByText(`showing ${NEIGHBOR_PAGE_SIZE} of ${many.length}`)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByText('show more (15)')); });
    expect(document.querySelectorAll('.node-detail__neighbor')).toHaveLength(many.length);
  });

  it('keeps the seed pointers and shows the error when the match lookup fails', async () => {
    matchProjectNodes.mockRejectedValue(new Error('boom'));
    await act(async () => { render(<NodeDetail projectId="1" node={CONTRACT} />); });
    await waitFor(() => expect(screen.getByText(/match lookup failed: boom/)).toBeInTheDocument());
    expect(screen.getByText('4 pointers')).toBeInTheDocument();
    expect(screen.getByText('no neighbors share a ref with this node')).toBeInTheDocument();
  });
});
