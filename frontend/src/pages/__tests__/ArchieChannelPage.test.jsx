// Path: src/pages/__tests__/ArchieChannelPage.test.jsx
// File: ArchieChannelPage.test.jsx
// Created: 2026-06-23
// Purpose: Tests for the cross-project Archie Channel view (DWB-440). Covers direct vs broadcast rendering (is_broadcast and the to_agent_id-null fallback), sender project, read-state from the canonical read_by named-reader array (single + multiple readers, empty => unread), empty state, and load failure. Mocks use Barry's frozen DWB-437 message shape; field mapping mirrors normalizeMessage in ArchieChannelPage.
// Caller: vitest test runner
// Callees: ../ArchieChannelPage, ../../api/tlChannel (mocked)
// Data In: Mocked getTLChannel responses
// Data Out: Test assertions
// Last Modified: 2026-06-23

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';

vi.mock('../../api/tlChannel', () => ({
  getTLChannel: vi.fn(),
}));

import ArchieChannelPage from '../ArchieChannelPage';
import { getTLChannel } from '../../api/tlChannel';

beforeEach(() => {
  getTLChannel.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('ArchieChannelPage (cross-project TL channel)', () => {
  it('renders a direct message with sender, project, recipient, body and read count', async () => {
    getTLChannel.mockResolvedValue([
      {
        id: 1,
        from_agent_id: 21,
        from_agent_name: 'Archie_DWB',
        from_project_id: 1,
        from_project_prefix: 'DWB',
        to_agent_id: 30,
        to_agent_name: 'Archie_CI',
        is_broadcast: false,
        body: 'Can you take the migration?',
        created_at: '2026-06-23T19:00:00',
        read_by: [
          { agent_id: 30, agent_name: 'Archie_CI', read_at: '2026-06-23T19:05:00' },
        ],
      },
    ]);

    render(<ArchieChannelPage />);

    expect(await screen.findByText('Can you take the migration?')).toBeInTheDocument();
    expect(screen.getByText('Archie_DWB')).toBeInTheDocument();
    expect(screen.getByText('DWB', { selector: '.tl-channel__project' })).toBeInTheDocument();
    expect(screen.getByText('Archie_CI', { selector: '.tl-channel__recipient' })).toBeInTheDocument();
    // read_by names render in the read-state column.
    expect(screen.getByText('Archie_CI', { selector: '.tl-channel__reader' })).toBeInTheDocument();
  });

  it('renders a broadcast message (to_agent_id null) with an ALL tag and broadcast styling', async () => {
    getTLChannel.mockResolvedValue([
      {
        id: 2,
        from_agent_id: 21,
        from_agent_name: 'Archie_DWB',
        from_project_id: 1,
        from_project_prefix: 'DWB',
        to_agent_id: null,
        to_agent_name: null,
        is_broadcast: true,
        body: 'Standup in 5.',
        created_at: '2026-06-23T19:05:00',
        read_by: [],
      },
    ]);

    const { container } = render(<ArchieChannelPage />);

    expect(await screen.findByText('Standup in 5.')).toBeInTheDocument();
    expect(screen.getByText('ALL')).toBeInTheDocument();
    expect(container.querySelector('.tl-channel__row--broadcast')).toBeTruthy();
    // empty read_by -> shows unread.
    expect(screen.getByText('unread')).toBeInTheDocument();
  });

  it('treats a message with to_agent_id null but no is_broadcast flag as broadcast', async () => {
    getTLChannel.mockResolvedValue([
      {
        id: 3,
        from_agent_name: 'Archie_CI',
        from_project_prefix: 'CI',
        to_agent_id: null,
        body: 'Heads up all.',
        created_at: '2026-06-23T19:10:00',
        read_by: [{ agent_id: 21, agent_name: 'Archie_DWB', read_at: '2026-06-23T19:11:00' }],
      },
    ]);

    render(<ArchieChannelPage />);

    expect(await screen.findByText('Heads up all.')).toBeInTheDocument();
    expect(screen.getByText('ALL')).toBeInTheDocument();
    expect(screen.getByText('Archie_DWB', { selector: '.tl-channel__reader' })).toBeInTheDocument();
  });

  it('renders multiple named readers from read_by', async () => {
    getTLChannel.mockResolvedValue([
      {
        id: 4,
        from_agent_name: 'Archie_DWB',
        from_project_prefix: 'DWB',
        to_agent_id: 47,
        to_agent_name: 'Archie_CI',
        is_broadcast: false,
        body: 'ping',
        created_at: '2026-06-23T19:50:00',
        read_by: [
          { agent_id: 47, agent_name: 'Archie_CI', read_at: '2026-06-23T19:55:00' },
          { agent_id: 50, agent_name: 'Archie_LAT', read_at: '2026-06-23T19:56:00' },
        ],
      },
    ]);

    render(<ArchieChannelPage />);

    expect(await screen.findByText('ping')).toBeInTheDocument();
    expect(screen.getByText('Archie_CI', { selector: '.tl-channel__reader' })).toBeInTheDocument();
    expect(screen.getByText('Archie_LAT', { selector: '.tl-channel__reader' })).toBeInTheDocument();
  });

  it('shows unread when read_by is an explicit empty array', async () => {
    getTLChannel.mockResolvedValue([
      {
        id: 5,
        from_agent_name: 'Archie_DWB',
        from_project_prefix: 'DWB',
        to_agent_id: null,
        is_broadcast: true,
        body: 'nobody read this',
        created_at: '2026-06-23T19:50:00',
        read_by: [],
      },
    ]);

    render(<ArchieChannelPage />);

    expect(await screen.findByText('nobody read this')).toBeInTheDocument();
    expect(screen.getByText('unread')).toBeInTheDocument();
  });

  it('shows the empty state when there are no messages', async () => {
    getTLChannel.mockResolvedValue([]);
    render(<ArchieChannelPage />);
    expect(await screen.findByText('No messages yet.')).toBeInTheDocument();
  });

  it('shows an unavailable state when the channel fails to load', async () => {
    getTLChannel.mockRejectedValue(new Error('boom'));
    render(<ArchieChannelPage />);
    await waitFor(() => {
      expect(screen.getByText('Channel unavailable.')).toBeInTheDocument();
    });
  });
});
