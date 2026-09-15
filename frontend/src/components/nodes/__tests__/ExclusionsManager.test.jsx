// Path: src/components/nodes/__tests__/ExclusionsManager.test.jsx
// File: ExclusionsManager.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the exclusions manager panel (DWB-552, browser panel per DWB-553): lists the project's rows as repo-relative patterns with no default marker, adds by free text and clears the field, renders the server's own rejection text for a duplicate or an absolute path without adding a row, deletes behind the project's inline-text confirm (delete -> confirm? yes / cancel, cancel restores), surfaces a failed delete while keeping the row, and fires the rescan handler behind its DWB-556 inline confirm, which must not nest a dialog. Bound to the live row shape {id, project_id, pattern, created_at} confirmed on 2026-09-15.
// Caller: vitest test runner
// Callees: ../ExclusionsManager, ../../../api/nodeExclusions (mocked)
// Data In: Mocked list/create/delete responses and ApiError-shaped rejections
// Data Out: Test assertions
// Last Modified: 2026-09-15 (DWB-556: rescan confirms first)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent } from '@testing-library/react';

vi.mock('../../../api/nodeExclusions', () => ({
  getNodeExclusions: vi.fn(),
  createNodeExclusion: vi.fn(),
  deleteNodeExclusion: vi.fn(),
  getRepoDirectories: vi.fn(),
}));

import ExclusionsManager from '../ExclusionsManager';
import {
  getNodeExclusions,
  createNodeExclusion,
  deleteNodeExclusion,
  getRepoDirectories,
} from '../../../api/nodeExclusions';

// The seven seeded rows on live project 1.
const ROWS = [
  { id: 1, project_id: 1, pattern: '.claude/', created_at: '2026-09-15T19:37:41' },
  { id: 2, project_id: 1, pattern: 'backend/tests/', created_at: '2026-09-15T19:37:41' },
  { id: 3, project_id: 1, pattern: '**/__tests__/', created_at: '2026-09-15T19:37:41' },
  { id: 4, project_id: 1, pattern: 'test_*.py', created_at: '2026-09-15T19:37:41' },
  { id: 5, project_id: 1, pattern: 'conftest.py', created_at: '2026-09-15T19:37:41' },
  { id: 6, project_id: 1, pattern: '*.test.js', created_at: '2026-09-15T19:37:41' },
  { id: 7, project_id: 1, pattern: '*.test.jsx', created_at: '2026-09-15T19:37:41' },
];

// The client turns a FastAPI {detail} body into error.message.
const apiError = (message) => Object.assign(new Error(message), { name: 'ApiError' });

const patterns = () => [...document.querySelectorAll('.exclusions__pattern')]
  .filter((el) => el.closest('.exclusions__row'))
  .map((el) => el.textContent);

async function renderManager(props = {}) {
  await act(async () => {
    render(<ExclusionsManager projectId="1" onRescan={() => {}} {...props} />);
  });
  await waitFor(() => expect(screen.getByTestId('exclusions-manager')).toBeInTheDocument());
}

describe('ExclusionsManager (DWB-552)', () => {
  beforeEach(() => {
    getNodeExclusions.mockReset();
    createNodeExclusion.mockReset();
    deleteNodeExclusion.mockReset();
    getRepoDirectories.mockReset();
    getRepoDirectories.mockResolvedValue({ parent: '', directories: [{ name: 'docs', path: 'docs' }] });
    getNodeExclusions.mockResolvedValue(ROWS);
  });

  afterEach(() => {
    cleanup();
  });

  it('lists every row as a repo-relative pattern with no default marker', async () => {
    await renderManager();
    await waitFor(() => expect(patterns()).toHaveLength(7));
    // display order is localeCompare on the pattern (verified against the real comparator)
    expect(patterns()).toEqual(['.claude/', '*.test.js', '*.test.jsx', '**/__tests__/', 'backend/tests/', 'conftest.py', 'test_*.py']);
    expect(getNodeExclusions).toHaveBeenCalledWith('1', expect.objectContaining({ signal: expect.anything() }));
    // seeded rows are ordinary rows: every one has its own delete control
    expect(screen.getAllByText('delete')).toHaveLength(7);
    expect(document.querySelector('.exclusions__count').textContent).toBe('7');
    // no absolute paths rendered anywhere
    expect(patterns().every((p) => !p.startsWith('/'))).toBe(true);
  });

  it('shows the empty state when nothing is excluded', async () => {
    getNodeExclusions.mockResolvedValue([]);
    await renderManager();
    await waitFor(() => expect(screen.getByText(/nothing excluded/)).toBeInTheDocument());
    expect(patterns()).toHaveLength(0);
  });

  it('adds by free text, clears the field, and shows the new row', async () => {
    const created = { id: 8, project_id: 1, pattern: 'docs/vendor/', created_at: '2026-09-15T19:50:00' };
    createNodeExclusion.mockResolvedValue(created);
    await renderManager();
    await waitFor(() => expect(patterns()).toHaveLength(7));

    const input = screen.getByLabelText('path or glob');
    const addBtn = screen.getByRole('button', { name: 'add' });
    expect(addBtn).toBeDisabled();

    await act(async () => { fireEvent.change(input, { target: { value: 'docs/vendor/' } }); });
    expect(addBtn).not.toBeDisabled();
    await act(async () => { fireEvent.click(addBtn); });

    expect(createNodeExclusion).toHaveBeenCalledWith('1', 'docs/vendor/');
    await waitFor(() => expect(patterns()).toContain('docs/vendor/'));
    expect(input.value).toBe('');
    expect(patterns()).toHaveLength(8);
  });

  it('renders the server rejection text and adds nothing on a duplicate or an absolute path', async () => {
    await renderManager();
    await waitFor(() => expect(patterns()).toHaveLength(7));
    const input = screen.getByLabelText('path or glob');

    createNodeExclusion.mockImplementation(() => Promise.reject(apiError("pattern already excluded for this project: '.claude/'")));
    await act(async () => { fireEvent.change(input, { target: { value: '.claude/' } }); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'add' })); });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent("pattern already excluded for this project: '.claude/'"));
    expect(patterns()).toHaveLength(7);
    expect(input.value).toBe('.claude/');

    createNodeExclusion.mockImplementation(() => Promise.reject(apiError("pattern must be repo-relative, not absolute: '/etc/passwd'")));
    await act(async () => { fireEvent.change(input, { target: { value: '/etc/passwd' } }); });
    // typing clears the previous error
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'add' })); });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('pattern must be repo-relative, not absolute'));
    expect(patterns()).toHaveLength(7);
  });

  it('deletes behind an inline text confirm, and cancel restores the control', async () => {
    deleteNodeExclusion.mockResolvedValue(null);
    await renderManager();
    await waitFor(() => expect(patterns()).toHaveLength(7));

    // cancel path first: no request, row stays
    const firstDelete = screen.getAllByText('delete')[0];
    await act(async () => { fireEvent.click(firstDelete); });
    expect(screen.getByText('cancel')).toBeInTheDocument();
    expect(screen.getByText(/confirm\?/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByText('cancel')); });
    expect(screen.queryByText(/confirm\?/)).not.toBeInTheDocument();
    expect(deleteNodeExclusion).not.toHaveBeenCalled();
    expect(patterns()).toHaveLength(7);

    // confirm path: deletes the row that control belongs to (sorted first is .claude/, id 1)
    await act(async () => { fireEvent.click(screen.getAllByText('delete')[0]); });
    await act(async () => { fireEvent.click(screen.getByText('yes')); });
    expect(deleteNodeExclusion).toHaveBeenCalledWith('1', 1);
    await waitFor(() => expect(patterns()).toHaveLength(6));
    expect(patterns()).not.toContain('.claude/');
    // no nested dialog was used
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the row and shows the error when a delete fails', async () => {
    deleteNodeExclusion.mockImplementation(() => Promise.reject(apiError('exclusion 1 not found for project 1')));
    await renderManager();
    await waitFor(() => expect(patterns()).toHaveLength(7));

    await act(async () => { fireEvent.click(screen.getAllByText('delete')[0]); });
    await act(async () => { fireEvent.click(screen.getByText('yes')); });
    await waitFor(() => expect(screen.getByText('exclusion 1 not found for project 1')).toBeInTheDocument());
    expect(patterns()).toHaveLength(7);
    // confirm collapsed back to the plain control
    expect(screen.queryByText(/confirm\?/)).not.toBeInTheDocument();
  });

  it('fires the rescan handler behind the inline confirm and disables the control while a pass runs', async () => {
    const onRescan = vi.fn();
    await renderManager({ onRescan });
    await waitFor(() => expect(patterns()).toHaveLength(7));

    // DWB-556: confirm in place, never a nested dialog
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'rescan now' })); });
    expect(screen.getByTestId('rescan-confirm')).toHaveTextContent('rescan? yes / cancel');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onRescan).not.toHaveBeenCalled();

    await act(async () => { fireEvent.click(screen.getByText('yes')); });
    expect(onRescan).toHaveBeenCalledTimes(1);

    cleanup();
    await renderManager({ onRescan, rescanning: true });
    await waitFor(() => expect(screen.getByRole('button', { name: 'rescanning...' })).toBeDisabled());
  });

  it('surfaces a list load failure', async () => {
    getNodeExclusions.mockImplementation(() => Promise.reject(apiError('boom')));
    await renderManager();
    await waitFor(() => expect(screen.getByText(/could not load exclusions: boom/)).toBeInTheDocument());
  });

  it('renders the real directory browser by default and lets browserSlot override it', async () => {
    await renderManager();
    await waitFor(() => expect(screen.getByTestId('dir-browser')).toBeInTheDocument());
    expect(getRepoDirectories).toHaveBeenCalledWith('1', '', expect.anything());

    cleanup();
    await renderManager({ browserSlot: <div data-testid="slot-override">swapped</div> });
    await waitFor(() => expect(screen.getByTestId('slot-override')).toBeInTheDocument());
    expect(screen.queryByTestId('dir-browser')).not.toBeInTheDocument();
  });

  it('a directory excluded from the browser lands in the list as a subtree pattern', async () => {
    const created = { id: 9, project_id: 1, pattern: 'docs/', created_at: '2026-09-15T20:10:00' };
    createNodeExclusion.mockResolvedValue(created);
    await renderManager();
    await waitFor(() => expect(screen.getByTestId('dir-browser')).toBeInTheDocument());

    const row = [...document.querySelectorAll('.dir-browser__row')][0];
    await act(async () => { fireEvent.click([...row.querySelectorAll('button')].find((b) => b.textContent === 'exclude')); });
    expect(createNodeExclusion).toHaveBeenCalledWith('1', 'docs/');
    await waitFor(() => expect(patterns()).toContain('docs/'));
  });
});
