// Path: src/__tests__/JournalPage.test.jsx
// File: JournalPage.test.jsx
// Created: 2026-09-30 (DWB-613)
// Purpose: Tests for the journal search page. Covers the filter-required
//          refusal shown client-side before any request, a successful
//          search rendering entries/tags/retrieval_count, the truncated
//          status note, and the empty-match state.
// Caller: vitest test runner
// Callees: ../pages/JournalPage, ../store/useStore (mocked), ../api/memory (mocked)
// Data In: Mocked store project + mocked searchJournal responses
// Data Out: Test assertions
// Last Modified: 2026-09-30 (DWB-613)

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/memory', () => ({
  searchJournal: vi.fn(),
}));

let mockState;
vi.mock('../store/useStore', () => ({
  default: (selector) => selector(mockState),
}));

import JournalPage from '../pages/JournalPage';
import { searchJournal } from '../api/memory';

function seed() {
  mockState = {
    projects: [{ id: 5, prefix: 'DWB', name: 'D Waantu B Guantu', memory_mode: 'human_memory' }],
  };
}

beforeEach(() => {
  searchJournal.mockReset();
  seed();
});

afterEach(() => {
  cleanup();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/5/journal']}>
      <Routes>
        <Route path="/projects/:id/journal" element={<JournalPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('JournalPage (DWB-613)', () => {
  it('refuses to search with no filter, without calling the API', () => {
    renderPage();
    fireEvent.click(screen.getByText('search'));

    expect(searchJournal).not.toHaveBeenCalled();
    expect(screen.getByTestId('journal-error')).toHaveTextContent('never read whole');
  });

  it('renders matched entries with tags and retrieval count', async () => {
    searchJournal.mockResolvedValue({
      status: 'complete', count: 1, total_matched: 1, filters_applied: ['term'],
      entries: [
        { id: 9, agent_id: 3, body: 'the fcntl lock blocks a second pytest run', tags: ['pytest', 'lock'], retrieval_count: 2, entered_at: '2026-09-30T12:00:00Z' },
      ],
    });
    renderPage();

    fireEvent.change(screen.getByPlaceholderText('term (substring of an entry)'), {
      target: { value: 'fcntl' },
    });
    fireEvent.click(screen.getByText('search'));

    await waitFor(() => expect(searchJournal).toHaveBeenCalledWith(
      expect.objectContaining({ term: 'fcntl' })
    ));

    expect(await screen.findByText('the fcntl lock blocks a second pytest run')).toBeInTheDocument();
    expect(screen.getByText('pytest')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('1 of 1 matched')).toBeInTheDocument();
  });

  it('shows the truncated note when more rows matched than returned', async () => {
    searchJournal.mockResolvedValue({
      status: 'truncated', count: 1, total_matched: 5, filters_applied: ['term'],
      entries: [{ id: 1, agent_id: 1, body: 'one of many', tags: [], retrieval_count: 0, entered_at: null }],
    });
    renderPage();

    fireEvent.change(screen.getByPlaceholderText('term (substring of an entry)'), {
      target: { value: 'many' },
    });
    fireEvent.click(screen.getByText('search'));

    expect(await screen.findByText(/1 of 5 matched/)).toBeInTheDocument();
    expect(screen.getByText(/narrow the search/)).toBeInTheDocument();
  });

  it('shows a clean empty state when nothing matched', async () => {
    searchJournal.mockResolvedValue({
      status: 'complete', count: 0, total_matched: 0, filters_applied: ['term'], entries: [],
    });
    renderPage();

    fireEvent.change(screen.getByPlaceholderText('term (substring of an entry)'), {
      target: { value: 'nothing' },
    });
    fireEvent.click(screen.getByText('search'));

    expect(await screen.findByTestId('journal-empty')).toHaveTextContent('no entries matched');
  });
});
