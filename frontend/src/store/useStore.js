// Path: src/store/useStore.js
// File: useStore.js
// Created: 2026-03-29
// Purpose: Central Zustand store managing all application state (projects, sprints, epics, agents, tickets, comments, alerts, instructions, test runs, activity log, polling)
// Caller: App.jsx, useAppData, usePolling, useActivityData, useAgentsData, useAlertsData, useCommentsData, useEpicsData, useInstructionsData, useProjectsData, useSprintsData, useTicketsData, and ~30 component files
// Callees: zustand, api/alerts, config
// Data In: Data set via setter functions from API fetch hooks
// Data Out: Exports useStore hook with state, setters, and computed getters
// Last Modified: 2026-03-29

import { create } from 'zustand';
import { updateAlert } from '../api/alerts';
import { POLLING_IDLE_INTERVAL } from '../config';

const useStore = create((set, get) => ({
  // Projects
  projects: [],
  setProjects: (projects) => set({ projects }),
  getProject: (id) => get().projects.find((p) => p.id === Number(id)),

  // Sprints
  sprints: [],
  setSprints: (sprints) => set({ sprints }),
  getSprintsByProject: (projectId) =>
    get().sprints.filter((s) => s.project_id === Number(projectId)),
  getSprint: (id) => get().sprints.find((s) => s.id === Number(id)),

  // Epics
  epics: [],
  setEpics: (epics) => set({ epics }),
  getEpicsByProject: (projectId) =>
    get().epics.filter((e) => e.project_id === Number(projectId)),
  getEpic: (id) => get().epics.find((e) => e.id === Number(id)),

  // Agents
  agents: [],
  setAgents: (agents) => set({ agents }),
  getAgent: (id) => get().agents.find((a) => a.id === Number(id)),

  // Project-Agent assignments
  projectAgents: [],
  setProjectAgents: (projectAgents) => set({ projectAgents }),
  getAgentsByProject: (projectId) => {
    const state = get();
    const agentIds = state.projectAgents
      .filter((pa) => pa.project_id === Number(projectId))
      .map((pa) => pa.agent_id);
    return state.agents.filter((a) => agentIds.includes(a.id));
  },

  // Tickets
  tickets: [],
  setTickets: (tickets) => set({ tickets }),
  getTicketsByProject: (projectId) =>
    get().tickets.filter((t) => t.project_id === Number(projectId)),
  getTicketsBySprint: (sprintId) =>
    get().tickets.filter((t) => t.sprint_id === Number(sprintId)),
  getTicketsByEpic: (epicId) =>
    get().tickets.filter((t) => t.epic_id === Number(epicId)),
  getTicketsByAgent: (agentId) =>
    get().tickets.filter((t) => t.assigned_agent_id === Number(agentId)),
  getTicket: (id) => get().tickets.find((t) => t.id === Number(id)),

  // Comments
  comments: [],
  setComments: (comments) => set({ comments }),
  getCommentsByTicket: (ticketId) =>
    get().comments.filter((c) => c.ticket_id === Number(ticketId)),

  // Alerts
  alerts: [],
  setAlerts: (alerts) => set({ alerts }),
  getOpenAlerts: () => get().alerts.filter((a) => a.status === 'open'),
  dismissAlert: (id) => {
    set((state) => ({
      alerts: state.alerts.map((a) =>
        a.id === id ? { ...a, status: 'acknowledged' } : a
      ),
    }));
    updateAlert(id, { status: 'acknowledged' }).catch(() => {});
  },

  // Instructions
  instructions: [],
  setInstructions: (instructions) => set({ instructions }),

  // Test Runs
  testRuns: [],
  setTestRuns: (testRuns) => set({ testRuns }),
  getTestRun: (id) => get().testRuns.find((r) => r.id === Number(id)),

  // Activity Log
  activityLog: [],
  setActivityLog: (activityLog) => set({ activityLog }),

  // Dashboard (computed from other data)
  getDashboard: () => {
    const state = get();
    return {
      total_projects: state.projects.length,
      total_agents: state.agents.length,
      active_agents: state.agents.filter((a) => a.is_active).length,
      total_tickets: state.tickets.length,
      tickets_done: state.tickets.filter((t) => t.status === 'done').length,
      tickets_in_progress: state.tickets.filter((t) => t.status === 'in_progress').length,
      open_alerts: state.alerts.filter((a) => a.status === 'open').length,
      total_tokens: state.tickets.reduce((sum, t) => sum + t.tokens_used, 0) +
        state.projects.reduce((sum, p) => sum + p.tl_overhead_tokens + p.pm_overhead_tokens, 0),
    };
  },

  // Polling
  polling: {
    interval: POLLING_IDLE_INTERVAL,
    isActive: false,
    lastUpdated: new Date().toISOString(),
  },
  setPollingInterval: (interval) =>
    set((state) => ({ polling: { ...state.polling, interval } })),
  setPollingActive: (isActive) =>
    set((state) => ({ polling: { ...state.polling, isActive } })),
  updateLastPolled: () =>
    set((state) => ({
      polling: { ...state.polling, lastUpdated: new Date().toISOString() },
    })),

  // Hook Sessions (passive tracking)
  hookSessions: [],
  setHookSessions: (hookSessions) => set({ hookSessions }),
  getHookSessionsByProject: (projectId) =>
    get().hookSessions.filter((s) => s.project_id === Number(projectId)),

  // Infra warnings (from /api/status)
  infraWarnings: [],
  setInfraWarnings: (warnings) => set({ infraWarnings: warnings || [] }),
}));

export default useStore;
