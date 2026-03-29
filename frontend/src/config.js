export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

export const POLLING_ACTIVE_INTERVAL = 2000;
export const POLLING_IDLE_INTERVAL = 10000;

export const ACTIVITY_LOG_LIMIT = 50;

export const ROLES = {
  TEAM_LEAD: 'team-lead',
  PM: 'pm',
};
