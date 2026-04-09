// Path: src/__tests__/store/useStore.test.js
// File: useStore.test.js
// Created: 2026-03-29
// Purpose: Unit tests for the Zustand store (setters, getters, computed selectors, polling)
// Caller: vitest test runner
// Callees: ../../store/useStore
// Data In: Sample data fixtures
// Data Out: Test assertions
// Last Modified: 2026-04-09

import { describe, it, expect, beforeEach } from 'vitest';
import useStore from '../../store/useStore';

// Reset store state before each test
beforeEach(() => {
  useStore.setState({
    projects: [],
    sprints: [],
    epics: [],
    agents: [],
    projectAgents: [],
    tickets: [],
    comments: [],
    alerts: [],
    instructions: [],
    testRuns: [],
    activityLog: [],
  });
});

// -- Sample data --
const projects = [
  { id: 1, name: 'Alpha', status: 'active', tl_overhead_tokens: 100, pm_overhead_tokens: 50 },
  { id: 2, name: 'Beta', status: 'paused', tl_overhead_tokens: 200, pm_overhead_tokens: 75 },
];

const agents = [
  { id: 1, name: 'Agent A', is_active: true },
  { id: 2, name: 'Agent B', is_active: false },
  { id: 3, name: 'Agent C', is_active: true },
];

const sprints = [
  { id: 1, project_id: 1, name: 'Sprint 1' },
  { id: 2, project_id: 1, name: 'Sprint 2' },
  { id: 3, project_id: 2, name: 'Sprint 3' },
];

const epics = [
  { id: 1, project_id: 1, name: 'Epic A' },
  { id: 2, project_id: 2, name: 'Epic B' },
];

const tickets = [
  { id: 1, project_id: 1, sprint_id: 1, epic_id: 1, assigned_agent_id: 1, status: 'done', tokens_used: 500 },
  { id: 2, project_id: 1, sprint_id: 2, epic_id: 1, assigned_agent_id: 2, status: 'in_progress', tokens_used: 300 },
  { id: 3, project_id: 2, sprint_id: 3, epic_id: 2, assigned_agent_id: 1, status: 'in_progress', tokens_used: 200 },
  { id: 4, project_id: 2, sprint_id: null, epic_id: null, assigned_agent_id: null, status: 'backlog', tokens_used: 0 },
];

const comments = [
  { id: 1, ticket_id: 1, body: 'Comment A' },
  { id: 2, ticket_id: 1, body: 'Comment B' },
  { id: 3, ticket_id: 2, body: 'Comment C' },
];

const alerts = [
  { id: 1, status: 'open', severity: 'warning' },
  { id: 2, status: 'open', severity: 'critical' },
  { id: 3, status: 'acknowledged', severity: 'info' },
];

const projectAgents = [
  { id: 1, project_id: 1, agent_id: 1 },
  { id: 2, project_id: 1, agent_id: 2 },
  { id: 3, project_id: 2, agent_id: 3 },
];


describe('Setters', () => {
  it('setProjects stores projects', () => {
    useStore.getState().setProjects(projects);
    expect(useStore.getState().projects).toEqual(projects);
  });

  it('setAgents stores agents', () => {
    useStore.getState().setAgents(agents);
    expect(useStore.getState().agents).toEqual(agents);
  });

  it('setTickets stores tickets', () => {
    useStore.getState().setTickets(tickets);
    expect(useStore.getState().tickets).toEqual(tickets);
  });
});


describe('getProject', () => {
  beforeEach(() => useStore.getState().setProjects(projects));

  it('returns project by numeric id', () => {
    expect(useStore.getState().getProject(1)).toEqual(projects[0]);
  });

  it('returns project by string id (coercion)', () => {
    expect(useStore.getState().getProject('2')).toEqual(projects[1]);
  });

  it('returns undefined for non-existent id', () => {
    expect(useStore.getState().getProject(999)).toBeUndefined();
  });
});


describe('getSprintsByProject', () => {
  beforeEach(() => useStore.getState().setSprints(sprints));

  it('returns sprints for project 1', () => {
    const result = useStore.getState().getSprintsByProject(1);
    expect(result).toHaveLength(2);
    expect(result.map((s) => s.id)).toEqual([1, 2]);
  });

  it('returns empty array for project with no sprints', () => {
    expect(useStore.getState().getSprintsByProject(999)).toEqual([]);
  });
});


describe('getEpicsByProject', () => {
  beforeEach(() => useStore.getState().setEpics(epics));

  it('returns epics for project 1', () => {
    expect(useStore.getState().getEpicsByProject(1)).toHaveLength(1);
  });

  it('handles string id', () => {
    expect(useStore.getState().getEpicsByProject('2')).toHaveLength(1);
  });
});


describe('Ticket getters', () => {
  beforeEach(() => useStore.getState().setTickets(tickets));

  it('getTicketsByProject filters by project_id', () => {
    const result = useStore.getState().getTicketsByProject(1);
    expect(result).toHaveLength(2);
    expect(result.every((t) => t.project_id === 1)).toBe(true);
  });

  it('getTicketsBySprint filters by sprint_id', () => {
    const result = useStore.getState().getTicketsBySprint(1);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(1);
  });

  it('getTicketsByEpic filters by epic_id', () => {
    const result = useStore.getState().getTicketsByEpic(1);
    expect(result).toHaveLength(2);
  });

  it('getTicketsByAgent filters by assigned_agent_id', () => {
    const result = useStore.getState().getTicketsByAgent(1);
    expect(result).toHaveLength(2);
    expect(result.every((t) => t.assigned_agent_id === 1)).toBe(true);
  });

  it('getTicket returns single ticket by id', () => {
    expect(useStore.getState().getTicket(3)).toEqual(tickets[2]);
  });

  it('getTicket returns undefined for missing id', () => {
    expect(useStore.getState().getTicket(999)).toBeUndefined();
  });
});


describe('getCommentsByTicket', () => {
  beforeEach(() => useStore.getState().setComments(comments));

  it('returns comments for ticket 1', () => {
    const result = useStore.getState().getCommentsByTicket(1);
    expect(result).toHaveLength(2);
  });

  it('returns empty for ticket with no comments', () => {
    expect(useStore.getState().getCommentsByTicket(999)).toEqual([]);
  });
});


describe('getOpenAlerts', () => {
  beforeEach(() => useStore.getState().setAlerts(alerts));

  it('returns only open alerts', () => {
    const result = useStore.getState().getOpenAlerts();
    expect(result).toHaveLength(2);
    expect(result.every((a) => a.status === 'open')).toBe(true);
  });
});


describe('getAgentsByProject', () => {
  beforeEach(() => {
    useStore.getState().setAgents(agents);
    useStore.getState().setProjectAgents(projectAgents);
  });

  it('returns agents assigned to project 1', () => {
    const result = useStore.getState().getAgentsByProject(1);
    expect(result).toHaveLength(2);
    expect(result.map((a) => a.id).sort()).toEqual([1, 2]);
  });

  it('returns agents assigned to project 2', () => {
    const result = useStore.getState().getAgentsByProject(2);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(3);
  });
});


describe('getDashboard', () => {
  beforeEach(() => {
    useStore.getState().setProjects(projects);
    useStore.getState().setAgents(agents);
    useStore.getState().setTickets(tickets);
    useStore.getState().setAlerts(alerts);
  });

  it('computes correct totals', () => {
    const dash = useStore.getState().getDashboard();
    expect(dash.total_projects).toBe(2);
    expect(dash.total_agents).toBe(3);
    expect(dash.active_agents).toBe(2);
    expect(dash.total_tickets).toBe(4);
    expect(dash.tickets_done).toBe(1);
    expect(dash.tickets_in_progress).toBe(2);
    expect(dash.open_alerts).toBe(2);
    // tokens: tickets(500+300+200+0) + projects(100+50+200+75) = 1425
    expect(dash.total_tokens).toBe(1425);
  });
});


describe('Test Runs', () => {
  const testRuns = [
    { id: 1, project_id: 1, suite: 'backend', status: 'passed', passed: 30, failed: 0 },
    { id: 2, project_id: 1, suite: 'frontend', status: 'failed', passed: 20, failed: 3 },
    { id: 3, project_id: 2, suite: 'backend', status: 'passed', passed: 15, failed: 0 },
  ];

  beforeEach(() => useStore.getState().setTestRuns(testRuns));

  it('setTestRuns stores test runs', () => {
    expect(useStore.getState().testRuns).toEqual(testRuns);
  });

  it('getTestRun returns run by numeric id', () => {
    expect(useStore.getState().getTestRun(1)).toEqual(testRuns[0]);
  });

  it('getTestRun returns run by string id (coercion)', () => {
    expect(useStore.getState().getTestRun('2')).toEqual(testRuns[1]);
  });

  it('getTestRun returns undefined for non-existent id', () => {
    expect(useStore.getState().getTestRun(999)).toBeUndefined();
  });
});


describe('Instructions', () => {
  const instructions = [
    { id: 1, scope: 'global', title: 'Instr A', body: 'body a' },
    { id: 2, scope: 'project', project_id: 1, title: 'Instr B', body: 'body b' },
  ];

  it('setInstructions stores instructions', () => {
    useStore.getState().setInstructions(instructions);
    expect(useStore.getState().instructions).toEqual(instructions);
  });
});


describe('Polling', () => {
  it('setPollingInterval updates interval', () => {
    useStore.getState().setPollingInterval(5000);
    expect(useStore.getState().polling.interval).toBe(5000);
  });

  it('setPollingActive updates isActive', () => {
    useStore.getState().setPollingActive(true);
    expect(useStore.getState().polling.isActive).toBe(true);
  });

  it('updateLastPolled sets a new timestamp', () => {
    const before = useStore.getState().polling.lastUpdated;
    useStore.getState().updateLastPolled();
    const after = useStore.getState().polling.lastUpdated;
    expect(after).not.toBe(before);
  });
});
