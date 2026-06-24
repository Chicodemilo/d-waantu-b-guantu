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

describe('ActivityFeed (scoring events, DWB-433 part 4)', () => {
  it('renders score_awarded as subject + signed positive delta + reason', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 20,
        action: 'score_awarded',
        entity_type: 'agent',
        entity_id: 21,
        details: { agent: 'Barry_DWB', delta: 10, source: 'human', reason: 'great catch' },
        agent_name: 'Archie_DWB',
        agent_role: 'team-lead',
        created_at: new Date().toISOString(),
      },
    ]);

    const { container } = renderFeed(1);

    const delta = await screen.findByText('+10');
    expect(delta.className).toContain('activity-feed__score--up');
    const activity = container.querySelector('.activity-feed__entry .activity-feed__col-activity');
    expect(activity.textContent.replace(/\s+/g, ' ').trim()).toBe('Barry_DWB +10 great catch');
  });

  it('renders score_docked with a signed negative delta', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 21,
        action: 'score_docked',
        entity_type: 'agent',
        entity_id: 19,
        details: { agent: 'Freddie', delta: -5, source: 'peer', reason: 'flaky test' },
        agent_name: 'Sage',
        agent_role: 'tester',
        created_at: new Date().toISOString(),
      },
    ]);

    const { container } = renderFeed(1);

    const delta = await screen.findByText('-5');
    expect(delta.className).toContain('activity-feed__score--down');
    const activity = container.querySelector('.activity-feed__entry .activity-feed__col-activity');
    expect(activity.textContent.replace(/\s+/g, ' ').trim()).toBe('Freddie -5 flaky test');
  });

  it('renders lead_change as a leader handoff', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 22,
        action: 'lead_change',
        entity_type: 'agent',
        entity_id: 21,
        details: { new_leader: 'Barry_DWB', previous_leader: 'Sage' },
        agent_name: null,
        agent_role: null,
        created_at: new Date().toISOString(),
      },
    ]);

    const { container } = renderFeed(1);

    await waitFor(() => expect(
      container.querySelector('.activity-feed__entry .activity-feed__col-activity').textContent.replace(/\s+/g, ' ').trim()
    ).toBe('Barry_DWB overtook Sage for #1'));
  });
});

describe('ActivityFeed (demoted test-run notice, DWB-464)', () => {
  it('renders test_run_requested as a "requested a test run" phrase', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 30,
        action: 'test_run_requested',
        entity_type: 'test_run',
        entity_id: 7,
        details: { triggered_by: 'Sage' },
        agent_name: 'Sage',
        agent_role: 'tester',
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText(/requested a test run: Sage/);
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders test_run_requested with no note when details are empty', async () => {
    getActivityFeed.mockResolvedValue([
      {
        id: 31,
        action: 'test_run_requested',
        entity_type: 'test_run',
        entity_id: 8,
        details: {},
        agent_name: 'system',
        agent_role: null,
        created_at: new Date().toISOString(),
      },
    ]);

    renderFeed(1);

    await screen.findByText('requested a test run');
  });
});
