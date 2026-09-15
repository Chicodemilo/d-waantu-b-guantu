// Path: src/components/nodes/__tests__/DirectoryBrowser.test.jsx
// File: DirectoryBrowser.test.jsx
// Created: 2026-09-15
// Purpose: Tests for the exclusions directory picker (DWB-552 over DWB-553): lists one level from the repo root, descends into a directory and builds a breadcrumb from the echoed parent, navigates up and by crumb, excludes a directory as a SUBTREE pattern with the trailing slash the endpoint does not add, marks directories already excluded, and surfaces the server's own error text without blanking the listing. Bound to the live shape {parent, directories[{name, path}]} confirmed on 2026-09-15.
// Caller: vitest test runner
// Callees: ../DirectoryBrowser, ../../../api/nodeExclusions (mocked)
// Data In: Mocked getRepoDirectories responses, onExclude spy
// Data Out: Test assertions
// Last Modified: 2026-09-15

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent } from '@testing-library/react';

vi.mock('../../../api/nodeExclusions', () => ({
  getNodeExclusions: vi.fn(),
  createNodeExclusion: vi.fn(),
  deleteNodeExclusion: vi.fn(),
  getRepoDirectories: vi.fn(),
}));

import DirectoryBrowser, { directoryPattern } from '../DirectoryBrowser';
import { getRepoDirectories } from '../../../api/nodeExclusions';

// Live listings from project 1.
const TREE = {
  '': { parent: '', directories: [
    { name: 'backend', path: 'backend' },
    { name: 'docs', path: 'docs' },
    { name: 'frontend', path: 'frontend' },
    { name: 'scripts', path: 'scripts' },
  ] },
  backend: { parent: 'backend', directories: [
    { name: 'alembic', path: 'backend/alembic' },
    { name: 'app', path: 'backend/app' },
    { name: 'scripts', path: 'backend/scripts' },
    { name: 'tests', path: 'backend/tests' },
  ] },
  'backend/app': { parent: 'backend/app', directories: [
    { name: 'models', path: 'backend/app/models' },
    { name: 'routers', path: 'backend/app/routers' },
  ] },
};

const apiError = (message) => Object.assign(new Error(message), { name: 'ApiError' });
const names = () => [...document.querySelectorAll('.dir-browser__name')].map((el) => el.textContent);
const rowFor = (label) => [...document.querySelectorAll('.dir-browser__row')]
  .find((r) => r.querySelector('.dir-browser__name').textContent === label);

async function renderBrowser(props = {}) {
  await act(async () => {
    render(<DirectoryBrowser projectId="1" onExclude={vi.fn().mockResolvedValue({ ok: true })} {...props} />);
  });
  await waitFor(() => expect(screen.getByTestId('dir-browser')).toBeInTheDocument());
}

describe('DirectoryBrowser (DWB-552 over DWB-553)', () => {
  beforeEach(() => {
    getRepoDirectories.mockReset();
    getRepoDirectories.mockImplementation((pid, parent) => Promise.resolve(TREE[parent || ''] || { parent, directories: [] }));
  });

  afterEach(() => {
    cleanup();
  });

  it('lists the repo root one level deep, directories only', async () => {
    await renderBrowser();
    await waitFor(() => expect(names()).toHaveLength(4));
    expect(names()).toEqual(['backend/', 'docs/', 'frontend/', 'scripts/']);
    expect(getRepoDirectories).toHaveBeenCalledWith('1', '', expect.objectContaining({ signal: expect.anything() }));
    // at the root there is nothing to go up to
    expect(screen.queryByText('up')).not.toBeInTheDocument();
  });

  it('descends, builds a breadcrumb, and navigates back by crumb and by up', async () => {
    await renderBrowser();
    await waitFor(() => expect(names()).toHaveLength(4));

    await act(async () => { fireEvent.click(screen.getByText('backend/')); });
    await waitFor(() => expect(names()).toEqual(['alembic/', 'app/', 'scripts/', 'tests/']));
    expect(getRepoDirectories).toHaveBeenLastCalledWith('1', 'backend', expect.anything());

    await act(async () => { fireEvent.click(screen.getByText('app/')); });
    await waitFor(() => expect(names()).toEqual(['models/', 'routers/']));
    // breadcrumb: repo root / backend / app
    const crumbs = [...document.querySelectorAll('.dir-browser__crumbs button')].map((b) => b.textContent);
    expect(crumbs).toEqual(['repo root', 'backend', 'app', 'up']);

    // up goes to backend
    await act(async () => { fireEvent.click(screen.getByText('up')); });
    await waitFor(() => expect(names()).toEqual(['alembic/', 'app/', 'scripts/', 'tests/']));

    // crumb jumps to the root
    await act(async () => { fireEvent.click(screen.getByText('repo root')); });
    await waitFor(() => expect(names()).toEqual(['backend/', 'docs/', 'frontend/', 'scripts/']));
  });

  it('excludes a directory as a subtree pattern, adding the trailing slash the endpoint does not', async () => {
    const onExclude = vi.fn().mockResolvedValue({ ok: true });
    await renderBrowser({ onExclude });
    await waitFor(() => expect(names()).toHaveLength(4));

    await act(async () => { fireEvent.click(screen.getByText('backend/')); });
    await waitFor(() => expect(names()).toContain('tests/'));

    const row = rowFor('tests/');
    await act(async () => { fireEvent.click([...row.querySelectorAll('button')].find((b) => b.textContent === 'exclude')); });
    expect(onExclude).toHaveBeenCalledWith('backend/tests/');
    expect(directoryPattern('backend/tests')).toBe('backend/tests/');
    expect(directoryPattern('backend/tests/')).toBe('backend/tests/');
    expect(directoryPattern('')).toBe('');
  });

  it('marks directories that are already excluded instead of offering the control', async () => {
    await renderBrowser({ excluded: new Set(['docs/', 'backend/tests/']) });
    await waitFor(() => expect(names()).toHaveLength(4));

    expect(rowFor('docs/').textContent).toContain('excluded');
    expect([...rowFor('docs/').querySelectorAll('button')].some((b) => b.textContent === 'exclude')).toBe(false);
    expect([...rowFor('backend/').querySelectorAll('button')].some((b) => b.textContent === 'exclude')).toBe(true);
  });

  it('shows the server rejection text when an exclude fails and keeps the listing', async () => {
    const onExclude = vi.fn().mockResolvedValue({ ok: false, error: "pattern already excluded for this project: 'docs/'" });
    await renderBrowser({ onExclude });
    await waitFor(() => expect(names()).toHaveLength(4));

    const row = rowFor('docs/');
    await act(async () => { fireEvent.click([...row.querySelectorAll('button')].find((b) => b.textContent === 'exclude')); });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent("pattern already excluded for this project: 'docs/'"));
    expect(names()).toHaveLength(4);
  });

  it('surfaces a listing failure without blanking what is already shown', async () => {
    await renderBrowser();
    await waitFor(() => expect(names()).toHaveLength(4));

    getRepoDirectories.mockImplementation(() => Promise.reject(apiError('directory not found: nope')));
    await act(async () => { fireEvent.click(screen.getByText('backend/')); });
    await waitFor(() => expect(screen.getByText(/could not list directories: directory not found: nope/)).toBeInTheDocument());
    expect(names()).toEqual(['backend/', 'docs/', 'frontend/', 'scripts/']);
  });

  it('shows an empty state for a directory with no subdirectories', async () => {
    getRepoDirectories.mockImplementation(() => Promise.resolve({ parent: 'scripts', directories: [] }));
    await renderBrowser();
    await waitFor(() => expect(screen.getByText('no subdirectories here.')).toBeInTheDocument());
  });
});
