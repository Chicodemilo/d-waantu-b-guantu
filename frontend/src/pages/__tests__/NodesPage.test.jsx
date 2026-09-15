// Path: src/pages/__tests__/NodesPage.test.jsx
// File: NodesPage.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the project Nodes cloud page (DWB-534/535/536): loading state, render of tag + pointer count with the head count line, log-bucket scaling classes (top nodes share the cap bucket), empty state pointing at POST /nodeify, the 500-node cap with show more / show all, click emitting a selection (aria-pressed), the selection opening the detail Overlay which closes on Esc / close / scrim and clears the selection, and the match search LIMITER (debounced, non-matching nodes disappear while matches keep their full-set bucket, query_tags line, no-match state, clear link and Esc restore the full cloud).
// Caller: vitest test runner
// Callees: ../NodesPage, ../../api/nodes (mocked: getProjectNodes + matchProjectNodes)
// Data In: Mocked getProjectNodes responses in the live NodeRead shape
// Data Out: Test assertions
// Last Modified: 2026-09-15 (DWB-536)

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
import { NODE_MATCH_DEBOUNCE_MS } from '../../hooks/useNodeMatch';

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

  describe('match search limiter (DWB-536)', () => {
    const MATCHES = {
      contract: { query_tags: ['contract'], ids: [517] },
      'review roster': { query_tags: ['review', 'roster'], ids: [1613, 1631] },
      'sprint close': { query_tags: ['sprint'], ids: [] },
    };

    function mockMatch() {
      matchProjectNodes.mockImplementation((pid, text) => {
        const hit = MATCHES[text] || { query_tags: [text], ids: [] };
        return Promise.resolve({
          query: text,
          query_tags: hit.query_tags,
          nodes: hit.ids.map((id) => ({ ...NODES.find((n) => n.id === id), neighbors: [] })),
        });
      });
    }

    async function renderLoaded() {
      getProjectNodes.mockResolvedValue(NODES);
      mockMatch();
      await act(async () => { renderAt(); });
      await waitFor(() => expect(screen.getByText('contract')).toBeInTheDocument());
      return screen.getByLabelText('match');
    }

    const visibleTags = () => [...document.querySelectorAll('.node-cloud__tag')].map((el) => el.textContent);
    // scoped to the cloud: the query_tags line renders the same words
    const bucketOf = (tag) => Number([...document.querySelectorAll('.node-cloud__node')].find((b) => b.querySelector('.node-cloud__tag').textContent === tag).dataset.bucket);

    it('limits the cloud to matching nodes after the debounce, keeping their full-set size, and shows query_tags', async () => {
      const input = await renderLoaded();
      const reviewBucketBefore = bucketOf('review');
      const rosterBucketBefore = bucketOf('roster');

      fireEvent.change(input, { target: { value: 'review roster' } });
      // before the debounce window elapses nothing is requested and the full cloud stays
      expect(matchProjectNodes).not.toHaveBeenCalled();
      expect(visibleTags()).toHaveLength(6);
      expect(screen.getByTestId('query-tags').textContent).toContain('matching...');

      await waitFor(() => expect(matchProjectNodes).toHaveBeenCalledTimes(1), { timeout: NODE_MATCH_DEBOUNCE_MS * 4 });
      expect(matchProjectNodes).toHaveBeenCalledWith('1', 'review roster', expect.anything());
      await waitFor(() => expect(visibleTags()).toEqual(['roster', 'review']));
      expect(visibleTags()).not.toContain('contract');
      expect(visibleTags()).not.toContain('zelda');
      // weight-scaled size preserved: same bucket as in the full cloud (not re-fit to the subset)
      expect(bucketOf('review')).toBe(reviewBucketBefore);
      expect(bucketOf('roster')).toBe(rosterBucketBefore);
      // query_tags line under the box
      const tags = [...document.querySelectorAll('.nodes-page__tag')].map((el) => el.textContent);
      expect(tags).toEqual(['review', 'roster']);
      expect(screen.getByText('2 / 6 matches')).toBeInTheDocument();
      expect(screen.getByText('showing 2 of 2')).toBeInTheDocument();
    });

    it('debounces keystrokes into one request for the final text', async () => {
      const input = await renderLoaded();
      fireEvent.change(input, { target: { value: 'c' } });
      fireEvent.change(input, { target: { value: 'con' } });
      fireEvent.change(input, { target: { value: 'contract' } });
      await waitFor(() => expect(visibleTags()).toEqual(['contract']), { timeout: NODE_MATCH_DEBOUNCE_MS * 4 });
      expect(matchProjectNodes).toHaveBeenCalledTimes(1);
      expect(matchProjectNodes).toHaveBeenCalledWith('1', 'contract', expect.anything());
    });

    it('zero matches shows an explicit no-match state with the normalized tags, and clear restores the full cloud', async () => {
      const input = await renderLoaded();
      fireEvent.change(input, { target: { value: 'sprint close' } });
      await waitFor(() => expect(screen.getByText(/no nodes match "sprint close"/)).toBeInTheDocument(), { timeout: NODE_MATCH_DEBOUNCE_MS * 4 });
      expect(screen.queryByTestId('node-cloud')).not.toBeInTheDocument();
      expect([...document.querySelectorAll('.nodes-page__tag')].map((el) => el.textContent)).toEqual(['sprint']);
      expect(screen.getByText('0 / 6 matches')).toBeInTheDocument();

      await act(async () => { fireEvent.click(screen.getByText('clear', { selector: '.fuzzy-search__clear' })); });
      expect(input.value).toBe('');
      expect(visibleTags()).toHaveLength(6);
      expect(screen.queryByTestId('query-tags')).not.toBeInTheDocument();
      expect(screen.queryByText(/no nodes match/)).not.toBeInTheDocument();
    });

    it('Esc inside the box empties the query and restores the full cloud', async () => {
      const input = await renderLoaded();
      fireEvent.change(input, { target: { value: 'contract' } });
      await waitFor(() => expect(visibleTags()).toEqual(['contract']), { timeout: NODE_MATCH_DEBOUNCE_MS * 4 });
      await act(async () => { fireEvent.keyDown(input, { key: 'Escape' }); });
      expect(input.value).toBe('');
      expect(visibleTags()).toHaveLength(6);
      expect(screen.getByText('showing 6 of 6')).toBeInTheDocument();
    });
  });
});
