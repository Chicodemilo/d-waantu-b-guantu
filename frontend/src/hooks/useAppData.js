// Path: src/hooks/useAppData.js
// File: useAppData.js
// Created: 2026-03-29
// Purpose: Master data-fetching hook that polls all API endpoints and hydrates the Zustand store
// Caller: App.jsx
// Callees: react, store/useStore, api/status, api/projects, api/sprints, api/epics, api/agents, api/tickets, api/comments, api/alerts, api/instructions, api/activityLogs, api/projectAgents, api/testResults, config
// Data In: None (reads polling intervals from config)
// Data Out: Exports useAppData hook; populates entire Zustand store via polling
// Last Modified: 2026-03-29

import { useEffect, useRef } from 'react';
import useStore from '../store/useStore';
import { getStatus } from '../api/status';
import { getProjects } from '../api/projects';
import { getSprints } from '../api/sprints';
import { getEpics } from '../api/epics';
import { getAgents } from '../api/agents';
import { getTickets } from '../api/tickets';
import { getComments } from '../api/comments';
import { getAlerts } from '../api/alerts';
import { getInstructions } from '../api/instructions';
import { getActivityLogs } from '../api/activityLogs';
import { getProjectAgents } from '../api/projectAgents';
import { getTestRuns } from '../api/testResults';
import { getHookSessions } from '../api/hooks';

import { POLLING_ACTIVE_INTERVAL, POLLING_IDLE_INTERVAL, ACTIVITY_LOG_LIMIT } from '../config';

function parseActivityDetails(item) {
  if (!item.details || typeof item.details !== 'string') return item;
  try {
    return { ...item, details: JSON.parse(item.details) };
  } catch {
    return item;
  }
}

function useAppData() {
  const store = useStore;
  const intervalRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      const state = store.getState();
      try {
        const [
          projects,
          sprints,
          epics,
          agents,
          tickets,
          comments,
          alerts,
          instructions,
          activityLogs,
          projectAgents,
          testRuns,
          hookSessions,
        ] = await Promise.all([
          getProjects(),
          getSprints(),
          getEpics(),
          getAgents(),
          getTickets(),
          getComments(),
          getAlerts(),
          getInstructions(),
          getActivityLogs({ limit: ACTIVITY_LOG_LIMIT }),
          getProjectAgents(),
          getTestRuns().catch(() => []),
          getHookSessions().catch(() => []),
        ]);

        if (cancelled) return;

        state.setProjects(projects);
        state.setSprints(sprints);
        state.setEpics(epics);
        state.setAgents(agents);
        state.setTickets(tickets);
        state.setComments(comments);
        state.setAlerts(alerts);
        state.setInstructions(instructions);
        state.setActivityLog(activityLogs.map(parseActivityDetails));
        state.setProjectAgents(projectAgents);
        state.setTestRuns(testRuns.map(parseActivityDetails));
        state.setHookSessions(hookSessions);
        state.updateLastPolled();
      } catch (err) {
        console.error('[useAppData] fetch error:', err);
      }
    }

    async function tick() {
      if (cancelled) return;
      const state = store.getState();

      let interval = POLLING_IDLE_INTERVAL;
      try {
        const status = await getStatus();
        interval =
          status.active_agents > 0 || status.in_progress_tickets > 0
            ? POLLING_ACTIVE_INTERVAL
            : POLLING_IDLE_INTERVAL;
        state.setPollingInterval(interval);
        state.setPollingActive(true);
        state.setInfraWarnings(status.infra_warnings);
      } catch (err) {
        console.error('[useAppData] status error:', err);
        state.setPollingActive(false);
      }

      await fetchAll();

      if (!cancelled) {
        intervalRef.current = setTimeout(tick, interval);
      }
    }

    tick();

    return () => {
      cancelled = true;
      if (intervalRef.current) clearTimeout(intervalRef.current);
    };
  }, []);
}

export default useAppData;
