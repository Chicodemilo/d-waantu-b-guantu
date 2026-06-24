// Path: src/__tests__/InterAgentCommsPage.test.jsx
// File: InterAgentCommsPage.test.jsx
// Created: 2026-06-24
// Purpose: Tests for the project-level Inter-Agent Comms glance view (DWB-451) - renders the small header + count, lists captured messages newest-first as the API returns them, shows from -> to and a timestamp, renders the body in the truncation cell (single-line ellipsis is CSS), and drives the inline-text Clear confirm flow (clear -> confirm? yes/cancel) calling the DELETE wrapper on yes.
// Caller: vitest test runner
// Callees: ../pages/InterAgentCommsPage, ../api/agentMessages (mocked)
// Data In: Mocked agentMessages API
// Data Out: Test assertions
// Last Modified: 2026-06-24

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api/agentMessages', () => ({
  getAgentMessages: vi.fn(),
  clearAgentMessages: vi.fn(),
}));

import InterAgentCommsPage from '../pages/InterAgentCommsPage';
import { getAgentMessages, clearAgentMessages } from '../api/agentMessages';

const ENVELOPE = {
  project_id: 1,
  total: 2,
  limit: 50,
  offset: 0,
  rows: [
    {
      id: 5,
      from_agent_id: null,
      from_agent_name: 'Pam_DWB',
      to_agent_id: null,
      to_agent_name: 'Barry',
      body: 'Backend contract confirmed.',
      summary: null,
      created_at: '2026-06-24T13:46:07',
      dwb_session_id: null,
    },
    {
      id: 4,
      from_agent_id: null,
      from_agent_name: 'Archie_DWB',
      to_agent_id: 19,
      to_agent_name: 'Freddie',
      body: 'A very long body that should be truncated to a single line with an ellipsis in the glance view.',
      summary: null,
      created_at: '2026-06-24T13:40:00',
      dwb_session_id: null,
    },
  ],
};

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/comms" element={<InterAgentCommsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('InterAgentCommsPage (DWB-451)', () => {
  beforeEach(() => {
    getAgentMessages.mockReset();
    clearAgentMessages.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the small header, count, and the messages with from -> to + body', async () => {
    getAgentMessages.mockResolvedValue(ENVELOPE);

    await act(async () => {
      renderAt('/projects/1/comms');
    });

    await waitFor(() => {
      expect(screen.getByText('Inter-Agent Comms')).toBeInTheDocument();
    });

    expect(screen.getByText('2 messages')).toBeInTheDocument();
    // newest-first as returned: senders + recipients shown
    expect(screen.getByText('Pam_DWB')).toBeInTheDocument();
    expect(screen.getByText('Barry')).toBeInTheDocument();
    expect(screen.getByText('Archie_DWB')).toBeInTheDocument();
    expect(screen.getByText('Freddie')).toBeInTheDocument();
    // body rendered in the (CSS-truncated) message cell
    expect(screen.getByText('Backend contract confirmed.')).toBeInTheDocument();
  });

  it('drives the inline-text Clear confirm flow and calls the DELETE wrapper on yes', async () => {
    getAgentMessages.mockResolvedValue(ENVELOPE);
    clearAgentMessages.mockResolvedValue({ deleted: 2 });

    await act(async () => {
      renderAt('/projects/1/comms');
    });

    await waitFor(() => {
      expect(screen.getByText('clear')).toBeInTheDocument();
    });

    // Clicking clear swaps to the inline confirm (no modal)
    fireEvent.click(screen.getByText('clear'));
    expect(screen.getByText('yes')).toBeInTheDocument();
    expect(screen.getByText('cancel')).toBeInTheDocument();

    // Cancel reverts in place
    fireEvent.click(screen.getByText('cancel'));
    expect(screen.getByText('clear')).toBeInTheDocument();
    expect(clearAgentMessages).not.toHaveBeenCalled();

    // Clear -> yes fires the DELETE
    fireEvent.click(screen.getByText('clear'));
    await act(async () => {
      fireEvent.click(screen.getByText('yes'));
    });
    expect(clearAgentMessages).toHaveBeenCalledWith('1');
  });

  it('shows an empty state when there are no messages', async () => {
    getAgentMessages.mockResolvedValue({ project_id: 1, total: 0, limit: 50, offset: 0, rows: [] });

    await act(async () => {
      renderAt('/projects/1/comms');
    });

    await waitFor(() => {
      expect(screen.getByText('No inter-agent messages captured yet.')).toBeInTheDocument();
    });
    // No clear control when there is nothing to clear
    expect(screen.queryByText('clear')).not.toBeInTheDocument();
  });
});
