// Path: src/pages/__tests__/NodesPage.test.jsx
// File: NodesPage.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the project Nodes cloud page (DWB-534/535/536/541/542/543): loading state, render of tag + pointer count with the head count line, log-bucket scaling classes (top nodes share the cap bucket), empty state pointing at POST /nodeify, the 500-node cap with show more / show all, click emitting a selection (aria-pressed), the selection opening the detail Overlay which closes on Esc / close / scrim and clears the selection, the client-side substring LIMITER (case-insensitive on tag, no server call, matches keep their full-set bucket and headliner tier, no-match state, clear link and Esc restore the full cloud), the + connections toggle (off by default, dimmed first-degree neighbors for a small match set, disabled above 25 matches), and the pointer-kind toggle row (only present kinds, toggling memory off hides code/doc-only nodes, all-off message with select all, composes with the search).
// Caller: vitest test runner
// Callees: ../NodesPage, ../../api/nodes (mocked: getProjectNodes + matchProjectNodes for connections)
// Data In: Mocked getProjectNodes responses in the live NodeRead shape
// Data Out: Test assertions
// Last Modified: 2026-09-15 (DWB-543)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../../api/nodes', () => ({
  getProjectNodes: vi.fn(),
  matchProjectNodes: vi.fn(),
}));

import NodesPage from '../NodesPage';
import { getProjectNodes, matchProjectNodes } from '../../api/nodes';
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
    matchProjectNodes.mockReset();
    matchProjectNodes.mockImplementation((pid, text) => Promise.resolve({ query: text, query_tags: [text], nodes: [] }));
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

  it('scales by log bucket: the heavy top nodes share the cap bucket, the lightest is bucket 0, and exactly ceil(2%) are headliners', async () => {
    getProjectNodes.mockResolvedValue(NODES);
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('contract')).toBeInTheDocument());

    const bucketOf = (tag) => Number(screen.getByText(tag).closest('button').dataset.bucket);
    // 6 nodes -> ceil(0.12) = 1 headliner: contract (first of the two weight-121 nodes in API order)
    expect(bucketOf('contract')).toBe(8);
    expect(screen.getByText('contract').closest('button')).toHaveClass('node-cloud__node--headliner');
    expect(document.querySelectorAll('.node-cloud__node--headliner')).toHaveLength(1);
    expect(bucketOf('roster')).toBe(7);
    expect(screen.getByText('roster').closest('button')).not.toHaveClass('node-cloud__node--headliner');
    expect(bucketOf('review')).toBe(7);
    expect(bucketOf('ticket-key')).toBe(7);
    expect(bucketOf('zelda')).toBe(0);
    const mid = bucketOf('middling');
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(7);
    expect(screen.getByText('contract').closest('button')).toHaveClass('node-cloud__node--b8');
    expect(screen.getByText('roster').closest('button')).toHaveClass('node-cloud__node--b7');
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

  it('selecting a node opens the detail overlay; Esc, close link, and scrim each close it and clear the selection', async () => {
    getProjectNodes.mockResolvedValue(NODES);
    matchProjectNodes.mockImplementation((pid, text) => Promise.resolve({
      query: text, query_tags: [text],
      nodes: [{ ...NODES.find((n) => n.tag === text), neighbors: [{ id: 7, tag: 'zelda', weight: 10, shared_refs: ['a'] }] }],
    }));
    await act(async () => { renderAt(); });
    await waitFor(() => expect(screen.getByText('review')).toBeInTheDocument());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    const open = async (tag) => {
      await act(async () => { fireEvent.click(screen.getByText(tag).closest('.node-cloud__node')); });
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
      expect(screen.getByRole('dialog')).toHaveAttribute('aria-label', `node ${tag}`);
      expect(within(screen.getByRole('dialog')).getByText(tag)).toHaveClass('node-detail__tag');
      expect(matchProjectNodes).toHaveBeenLastCalledWith('1', tag, expect.anything());
    };

    await open('review');
    await act(async () => { fireEvent.keyDown(document, { key: 'Escape' }); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('review').closest('.node-cloud__node')).toHaveAttribute('aria-pressed', 'false');

    await open('contract');
    await act(async () => { fireEvent.click(screen.getByText('close')); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await open('roster');
    await act(async () => { fireEvent.click(screen.getByTestId('overlay-scrim')); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  describe('substring search limiter + connections (DWB-536/543)', () => {
    async function renderLoaded() {
      getProjectNodes.mockResolvedValue(NODES);
      matchProjectNodes.mockImplementation((pid, text) => {
        const hit = NODES.find((n) => n.tag === text);
        const neighbors = text === 'contract' ? [{ id: 7, tag: 'zelda', weight: 10, shared_refs: ['a'] }, { id: 42, tag: 'middling', weight: 25, shared_refs: ['b'] }] : [];
        return Promise.resolve({ query: text, query_tags: [text], nodes: hit ? [{ ...hit, neighbors }] : [] });
      });
      await act(async () => { renderAt(); });
      await waitFor(() => expect(screen.getByText('contract')).toBeInTheDocument());
      return screen.getByLabelText('match');
    }

    const visibleTags = () => [...document.querySelectorAll('.node-cloud__tag')].map((el) => el.textContent);
    const nodeBtn = (tag) => [...document.querySelectorAll('.node-cloud__node')].find((b) => b.querySelector('.node-cloud__tag').textContent === tag);
    const bucketOf = (tag) => Number(nodeBtn(tag).dataset.bucket);
    const toggle = () => screen.getByRole('button', { name: '+ connections' });

    it('filters by case-insensitive substring on the tag with no server call, keeping full-set size and headliner', async () => {
      const input = await renderLoaded();
      const reviewBucketBefore = bucketOf('review');
      await act(async () => { fireEvent.change(input, { target: { value: 'R' } }); });
      // contract, roster, review all contain "r"; ticket-key, middling, zelda do not
      expect(visibleTags()).toEqual(['contract', 'roster', 'review']);
      expect(matchProjectNodes).not.toHaveBeenCalled();
      expect(bucketOf('review')).toBe(reviewBucketBefore);
      expect(bucketOf('contract')).toBe(8);
      expect(screen.getByText('3 / 6 matches')).toBeInTheDocument();
      expect(screen.getByText('showing 3 of 3')).toBeInTheDocument();
      // "con" shows every tag containing con
      await act(async () => { fireEvent.change(input, { target: { value: 'con' } }); });
      expect(visibleTags()).toEqual(['contract']);
      expect(screen.getByText('1 / 6 match')).toBeInTheDocument();
      // no query_tags line any more
      expect(screen.queryByTestId('query-tags')).not.toBeInTheDocument();
    });

    it('a limited cloud without the headliner does not promote a new one', async () => {
      const input = await renderLoaded();
      await act(async () => { fireEvent.change(input, { target: { value: 'ling' } }); });
      expect(visibleTags()).toEqual(['middling']);
      expect(document.querySelectorAll('.node-cloud__node--headliner')).toHaveLength(0);
    });

    it('zero matches shows the no-match state; clear link and Esc restore the full cloud', async () => {
      const input = await renderLoaded();
      await act(async () => { fireEvent.change(input, { target: { value: 'zzzz' } }); });
      expect(screen.getByText(/no nodes match "zzzz"/)).toBeInTheDocument();
      expect(screen.queryByTestId('node-cloud')).not.toBeInTheDocument();
      expect(screen.getByText('0 / 6 matches')).toBeInTheDocument();
      await act(async () => { fireEvent.click(screen.getByText('clear', { selector: '.fuzzy-search__clear' })); });
      expect(input.value).toBe('');
      expect(visibleTags()).toHaveLength(6);
      await act(async () => { fireEvent.change(input, { target: { value: 'ros' } }); });
      expect(visibleTags()).toEqual(['roster']);
      await act(async () => { fireEvent.keyDown(input, { key: 'Escape' }); });
      expect(input.value).toBe('');
      expect(screen.getByText('showing 6 of 6')).toBeInTheDocument();
    });

    it('connections toggle is off by default and disabled without a search', async () => {
      await renderLoaded();
      expect(toggle()).toBeDisabled();
      expect(toggle()).toHaveAttribute('aria-pressed', 'false');
      expect(matchProjectNodes).not.toHaveBeenCalled();
    });

    it('connections on adds dimmed first-degree neighbors around a small match set and composes with the kind filter', async () => {
      const input = await renderLoaded();
      await act(async () => { fireEvent.change(input, { target: { value: 'contract' } }); });
      expect(visibleTags()).toEqual(['contract']);
      expect(toggle()).not.toBeDisabled();
      await act(async () => { fireEvent.click(toggle()); });
      await waitFor(() => expect(screen.getByText('2 connections shown')).toBeInTheDocument());
      expect(matchProjectNodes).toHaveBeenCalledTimes(1);
      expect(matchProjectNodes).toHaveBeenCalledWith('1', 'contract', expect.anything());
      // API order kept: contract, then the neighbors middling and zelda
      expect(visibleTags()).toEqual(['contract', 'middling', 'zelda']);
      expect(nodeBtn('zelda')).toHaveClass('node-cloud__node--connected');
      expect(nodeBtn('middling')).toHaveClass('node-cloud__node--connected');
      expect(nodeBtn('contract')).not.toHaveClass('node-cloud__node--connected');
      // the count still reports matches only
      expect(screen.getByText('1 / 6 match')).toBeInTheDocument();
      // connected neighbors still obey the kind filter: the fixture has only code pointers, so
      // code off is the all-kinds-off state and nothing (matches or connections) renders
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /^code/ })); });
      expect(screen.getByText(/no kinds selected/)).toBeInTheDocument();
      expect(screen.queryByTestId('node-cloud')).not.toBeInTheDocument();
      const links = screen.getAllByText('select all');
      await act(async () => { fireEvent.click(links[links.length - 1]); });
      expect(visibleTags()).toEqual(['contract', 'middling', 'zelda']);
      // toggling off removes the neighbors without another request
      await act(async () => { fireEvent.click(toggle()); });
      expect(visibleTags()).toEqual(['contract']);
      expect(matchProjectNodes).toHaveBeenCalledTimes(1);
    });

    it('connections toggle is disabled above 25 matches with the narrow-the-search title', async () => {
      const many = Array.from({ length: 30 }, (_, i) => node(i + 1, `x-tag-${i + 1}`, 50, 1));
      getProjectNodes.mockResolvedValue(many);
      await act(async () => { renderAt(); });
      await waitFor(() => expect(screen.getByText('x-tag-1')).toBeInTheDocument());
      const input = screen.getByLabelText('match');
      await act(async () => { fireEvent.change(input, { target: { value: 'x-tag' } }); });
      expect(visibleTags()).toHaveLength(30);
      expect(toggle()).toBeDisabled();
      expect(toggle()).toHaveAttribute('title', 'narrow the search to show connections');
      await act(async () => { fireEvent.click(toggle()); });
      expect(matchProjectNodes).not.toHaveBeenCalled();
      // narrowing to 25 or fewer enables it
      await act(async () => { fireEvent.change(input, { target: { value: 'x-tag-1' } }); });
      expect(visibleTags()).toHaveLength(11); // x-tag-1, x-tag-10..x-tag-19
      expect(toggle()).not.toBeDisabled();
    });
  });

  describe('pointer-kind toggles (DWB-542)', () => {
    const KP = (id, kind) => ({ id, kind, ref: `r${id}`, sha: 'x', line_start: 1, line_end: 1 });
    const KIND_NODES = [
      { id: 1, project_id: 1, tag: 'alpha', weight: 100, pointers: [KP(11, 'code'), KP(12, 'memory')] },
      { id: 2, project_id: 1, tag: 'bravo', weight: 60, pointers: [KP(21, 'code'), KP(22, 'doc')] },
      { id: 3, project_id: 1, tag: 'charlie', weight: 30, pointers: [KP(31, 'doc')] },
      { id: 4, project_id: 1, tag: 'delta', weight: 10, pointers: [KP(41, 'memory')] },
    ];
    const visibleTags = () => [...document.querySelectorAll('.node-cloud__tag')].map((el) => el.textContent);
    const toggle = (label) => screen.getByRole('button', { name: new RegExp(`^${label}`) });

    async function renderKinds() {
      getProjectNodes.mockResolvedValue(KIND_NODES);
      matchProjectNodes.mockImplementation((pid, text) => Promise.resolve({
        query: text, query_tags: [text],
        nodes: KIND_NODES.filter((n) => n.tag === text).map((n) => ({ ...n, neighbors: [] })),
      }));
      await act(async () => { renderAt(); });
      await waitFor(() => expect(screen.getByText('alpha')).toBeInTheDocument());
    }

    it('renders a button per present kind (docs label), all pressed initially, with node counts', async () => {
      await renderKinds();
      const row = screen.getByTestId('kind-filter');
      const buttons = [...row.querySelectorAll('.kind-filter__toggle')];
      expect(buttons.map((b) => b.textContent)).toEqual(['code2', 'docs2', 'memory2']);
      expect(buttons.every((b) => b.getAttribute('aria-pressed') === 'true')).toBe(true);
      expect(screen.queryByText('select all')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^ticket/ })).not.toBeInTheDocument();
    });

    it('toggling memory off hides nodes with only code and doc pointers', async () => {
      await renderKinds();
      await act(async () => { fireEvent.click(toggle('code')); });
      await act(async () => { fireEvent.click(toggle('docs')); });
      expect(toggle('code')).toHaveAttribute('aria-pressed', 'false');
      expect(toggle('memory')).toHaveAttribute('aria-pressed', 'true');
      // only memory on: alpha (code+memory) and delta (memory) stay; bravo (code+doc) and charlie (doc) go
      expect(visibleTags()).toEqual(['alpha', 'delta']);
      expect(screen.getByText('select all')).toBeInTheDocument();
      // and the reverse: memory off alone hides the memory-only node
      await act(async () => { fireEvent.click(screen.getByText('select all')); });
      await act(async () => { fireEvent.click(toggle('memory')); });
      expect(visibleTags()).toEqual(['alpha', 'bravo', 'charlie']);
      expect(toggle('memory')).toHaveClass('kind-filter__toggle');
      expect(toggle('memory')).not.toHaveClass('kind-filter__toggle--on');
    });

    it('all kinds off shows "no kinds selected" with a working select all link', async () => {
      await renderKinds();
      for (const label of ['code', 'docs', 'memory']) {
        await act(async () => { fireEvent.click(toggle(label)); });
      }
      expect(screen.getByText(/no kinds selected/)).toBeInTheDocument();
      expect(screen.queryByTestId('node-cloud')).not.toBeInTheDocument();
      const links = screen.getAllByText('select all');
      await act(async () => { fireEvent.click(links[links.length - 1]); });
      expect(screen.queryByText(/no kinds selected/)).not.toBeInTheDocument();
      expect(visibleTags()).toHaveLength(4);
      expect([...document.querySelectorAll('.kind-filter__toggle')].every((b) => b.getAttribute('aria-pressed') === 'true')).toBe(true);
    });

    it('composes with the search: both filters must pass', async () => {
      await renderKinds();
      fireEvent.change(screen.getByLabelText('match'), { target: { value: 'alpha' } });
      await waitFor(() => expect(visibleTags()).toEqual(['alpha']));
      // alpha has code + memory; turning both off leaves only docs, which alpha lacks -> no-match state
      await act(async () => { fireEvent.click(toggle('code')); });
      expect(visibleTags()).toEqual(['alpha']);
      await act(async () => { fireEvent.click(toggle('memory')); });
      expect(visibleTags()).toEqual([]);
      expect(screen.getByText(/no nodes match "alpha"/)).toBeInTheDocument();
      // re-enable memory: alpha returns, still limited by the search
      await act(async () => { fireEvent.click(toggle('memory')); });
      expect(visibleTags()).toEqual(['alpha']);
      expect(screen.getByText('1 / 4 match')).toBeInTheDocument();
    });
  });
});
