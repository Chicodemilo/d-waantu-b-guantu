// Path: src/pages/__tests__/DocsPage.test.jsx
// File: DocsPage.test.jsx
// Created: 2026-09-17
// Purpose: Branch guard for DocsPage (DWB-574). The page used to decide "is this
//          the dashboard's own project" with project.prefix === 'DWB', which is
//          correct here only because the prefix happens to be DWB: on a clone
//          that named the project anything else the redirect silently never
//          fired and the page took the wrong branch forever. These tests pin the
//          branch to the resolved-path answer the API supplies (runs_own_tests)
//          by driving the two cases where prefix and repo identity DISAGREE, so
//          a prefix comparison cannot satisfy them.
// Caller: vitest test runner
// Callees: ../DocsPage, ../../api/docs (mocked), ../../store/useStore
// Data In: Mocked getProjectDocs responses, project rows pushed into the store
// Data Out: Test assertions
// Last Modified: 2026-09-17

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../../api/docs', () => ({
  getProjectDocs: vi.fn(),
  getSystemDocs: vi.fn(),
}));

import DocsPage from '../DocsPage';
import { getProjectDocs } from '../../api/docs';
import useStore from '../../store/useStore';

const SERVER_REPO = '/Users/someone/dev/d-waantu_b-guantu';

function renderAt(projectId) {
  return render(
    <MemoryRouter initialEntries={[`/projects/${projectId}/docs`]}>
      <Routes>
        <Route path="/projects/:id/docs" element={<DocsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  getProjectDocs.mockReset();
  getProjectDocs.mockResolvedValue([
    { name: 'README.md', path: `${SERVER_REPO}/README.md`, exists: true, content: '# readme' },
  ]);
  useStore.setState({ projects: [] });
});

afterEach(() => {
  cleanup();
});

describe('DocsPage own-repo branch (DWB-574)', () => {
  it('redirects to system docs when the project IS the dashboard repo, whatever it is called', async () => {
    // The decisive case: prefix is NOT 'DWB', so a prefix comparison takes the
    // wrong branch here. This is what a clone looks like.
    useStore.setState({
      projects: [
        { id: 7, prefix: 'PORTAL', name: 'Portal', repo_path: SERVER_REPO, runs_own_tests: true },
      ],
    });

    renderAt(7);

    expect(
      await screen.findByText(/docs are the system docs/)
    ).toBeInTheDocument();
    // The redirect branch must not also go fetching repo docs.
    expect(getProjectDocs).not.toHaveBeenCalled();
  });

  it('does NOT redirect a tracked project that merely happens to be called DWB', async () => {
    // The mirror case: prefix IS 'DWB' but the repo is somewhere else entirely,
    // so a prefix comparison wrongly swallows a real project's docs.
    useStore.setState({
      projects: [
        { id: 9, prefix: 'DWB', name: 'A tracked project', repo_path: '/somewhere/else', runs_own_tests: false },
      ],
    });

    renderAt(9);

    expect(await screen.findByText('README.md')).toBeInTheDocument();
    expect(screen.queryByText(/docs are the system docs/)).not.toBeInTheDocument();
    await waitFor(() => expect(getProjectDocs).toHaveBeenCalledWith('9'));
  });

  it('treats a missing runs_own_tests as a normal tracked project', async () => {
    // Absent field must not be read as truthy: an older cached project row
    // should fall through to the ordinary docs path, not the redirect.
    useStore.setState({
      projects: [{ id: 3, prefix: 'CI', name: 'CI', repo_path: '/somewhere/ci' }],
    });

    renderAt(3);

    expect(await screen.findByText('README.md')).toBeInTheDocument();
    expect(screen.queryByText(/docs are the system docs/)).not.toBeInTheDocument();
  });

  it('names no project in the redirect copy, so the sentence survives a clone', async () => {
    useStore.setState({
      projects: [
        { id: 7, prefix: 'PORTAL', name: 'Portal', repo_path: SERVER_REPO, runs_own_tests: true },
      ],
    });

    const { container } = renderAt(7);
    await screen.findByText(/docs are the system docs/);

    const copy = container.querySelector('.docs-redirect').textContent;
    expect(copy).toMatch(/the repo the dashboard itself runs from/);
    // The whole point of the fix: the rule, not an identity.
    expect(copy).not.toMatch(/\bDWB\b/);
  });
});
