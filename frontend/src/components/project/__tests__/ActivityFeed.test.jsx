// Path: src/components/project/__tests__/ActivityFeed.test.jsx
// File: ActivityFeed.test.jsx
// Created: 2026-06-19
// Purpose: Tests for DWB-407 type-aware + DWB-412 semantic-verb rendering on the live ProjectPage activity feed. Covers ticket link, alert title, sprint name, generic fallback, project scoping, empty state, plus the 8 semantic verbs (status_changed, reopened, assigned, sprint_opened, sprint_closed, consolidation_acked, session_opened, session_closed).
// Caller: vitest test runner
// Callees: ../ActivityFeed, ../../../api/activityFeed (mocked), react-router-dom (MemoryRouter)
// Data In: Mocked getActivityFeed responses
// Data Out: Test assertions
// Last Modified: 2026-06-22

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../api/activityFeed', () => ({
  getActivityFeed: vi.fn(),
}));

import ActivityFeed from '../ActivityFeed';
import { getActivityFeed } from '../../../api/activityFeed';

function renderFeed(projectId = 1) {
  return render(
    <MemoryRouter>
      <ActivityFeed projectId={projectId} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  getActivityFeed.mockReset();
});

afterEach(() => {
  cleanup();
});

describe('ActivityFeed (live, type-aware)', () => {
  it('renders a ticket entry as a link to the ticket detail page', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 1,
        action: 'updated',
        entity_type: 'ticket',
        entity_id: 937,
        details: { ticket_key: 'DWB-407', title: 'Mount type-aware renderer' },
        agent_name: 'Freddie',
        agent_role: 'frontend-worker',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    const link = await screen.findByRole('link', { name: /DWB-407/ });
    expect(link).toHaveAttribute('href', '/projects/1/tickets/937');
    expect(link).toHaveTextContent('Mount type-aware renderer');
  });

  it('renders an alert entry with its title and no link', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 2,
        action: 'raised',
        entity_type: 'alert',
        entity_id: 50,
        details: { title: 'Ticket closed with 0 tokens' },
        agent_name: 'system',
        agent_role: null,
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/raised alert: Ticket closed with 0 tokens/);
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders a sprint entry with its name', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 3,
        action: 'closed',
        entity_type: 'sprint',
        entity_id: 107,
        details: { name: 'Activity Feed Polish' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/closed Activity Feed Polish/);
  });

  it('falls back to generic action + type + detail for unknown entity types', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 4,
        action: 'updated',
        entity_type: 'epic',
        entity_id: 21,
        details: { summary: 'Phase two kicked off' },
        agent_name: 'Barry_DWB',
        agent_role: 'backend-worker',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText('updated epic Phase two kicked off');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('scopes the ticket link to the feed projectId', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 5,
        action: 'created',
        entity_type: 'ticket',
        entity_id: 942,
        details: { ticket_key: 'DWB-412', title: 'Extend renderer' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(7);

    const link = await screen.findByRole('link', { name: /DWB-412/ });
    expect(link).toHaveAttribute('href', '/projects/7/tickets/942');
  });

  it('shows the empty state when there is no activity', async () => {
    getActivityFeed.mockResolvedValue([]);

    renderFeed(1);

    await screen.findByText('No recent activity');
  });
});

describe('ActivityFeed (semantic verbs, DWB-412)', () => {
  it('renders status_changed as a moved phrase with the from/to transition, ticket linked by id', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 10,
        action: 'status_changed',
        entity_type: 'ticket',
        entity_id: 939,
        details: { from: 'in_review', to: 'done' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    // No ticket_key/title in details -> falls back to "ticket #939", linked.
    const link = await screen.findByRole('link', { name: /ticket #939/ });
    expect(link).toHaveAttribute('href', '/projects/1/tickets/939');
    await screen.findByText(/moved/);
    await screen.findByText(/from in_review to done/);
  });

  it('renders reopened with the parenthetical transition', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 11,
        action: 'reopened',
        entity_type: 'ticket',
        entity_id: 800,
        details: { from: 'done', to: 'in_progress' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/reopened/);
    await screen.findByText(/\(done to in_progress\)/);
    expect(screen.getByRole('link', { name: /ticket #800/ })).toHaveAttribute(
      'href',
      '/projects/1/tickets/800'
    );
  });

  it('renders assigned with the target agent name', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 12,
        action: 'assigned',
        entity_type: 'ticket',
        entity_id: 942,
        details: { agent: 'Freddie', agent_id: 19 },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/assigned/);
    await screen.findByText(/to Freddie/);
    expect(screen.getByRole('link', { name: /ticket #942/ })).toBeInTheDocument();
  });

  it('renders sprint_opened with sprint number and goal', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 13,
        action: 'sprint_opened',
        entity_type: 'sprint',
        entity_id: 115,
        details: { sprint_number: 67, goal: 'Semantic activity feed' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/opened sprint 67: Semantic activity feed/);
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders sprint_closed with sprint number and goal', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 14,
        action: 'sprint_closed',
        entity_type: 'sprint',
        entity_id: 107,
        details: { sprint_number: 66, goal: 'De-ceremony batch' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/closed sprint 66: De-ceremony batch/);
  });

  it('renders consolidation_acked with the sprint id', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 15,
        action: 'consolidation_acked',
        entity_type: 'agent',
        entity_id: 21,
        details: { sprint_id: 107 },
        agent_name: 'Barry_DWB',
        agent_role: 'backend-worker',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/acked consolidation \(sprint 107\)/);
  });

  it('renders session_opened with the session id and open method', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 16,
        action: 'session_opened',
        entity_type: 'session',
        entity_id: 36,
        details: { open_method: 'regex' },
        agent_name: null,
        agent_role: null,
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/opened DWB session #36 \(regex\)/);
  });

  it('renders session_closed with the session id and headline', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 17,
        action: 'session_closed',
        entity_type: 'session',
        entity_id: 36,
        details: { close_method: 'slash', headline: 'Shipped semantic feed', total_tokens: 48000 },
        agent_name: null,
        agent_role: null,
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/closed DWB session #36: Shipped semantic feed/);
  });
});
