// Path: src/components/tickets/TicketFilters.jsx
// File: TicketFilters.jsx
// Created: 2026-03-29
// Purpose: Filter controls for ticket list (status, type, sprint, epic, agent dropdowns)
// Caller: TicketList.jsx
// Callees: useStore, tickets.css
// Data In: projectId prop, filters object prop, onChange callback prop
// Data Out: default export TicketFilters component
// Last Modified: 2026-03-29

import useStore from '../../store/useStore';
import '../../styles/tickets.css';

function TicketFilters({ projectId, filters, onChange }) {
  const sprints = useStore((s) => s.getSprintsByProject(projectId));
  const epics = useStore((s) => s.getEpicsByProject(projectId));
  const agents = useStore((s) => s.agents);

  const statuses = ['all', 'backlog', 'todo', 'in_progress', 'in_review', 'done'];
  const types = ['all', 'task', 'bug', 'story', 'subtask'];

  const handleChange = (key, value) => {
    onChange({ ...filters, [key]: value });
  };

  return (
    <div className="ticket-filters">
      <div className="ticket-filters__group">
        <label className="ticket-filters__label">Status</label>
        <select
          className="ticket-filters__select"
          value={filters.status || 'all'}
          onChange={(e) => handleChange('status', e.target.value)}
        >
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>
      <div className="ticket-filters__group">
        <label className="ticket-filters__label">Type</label>
        <select
          className="ticket-filters__select"
          value={filters.type || 'all'}
          onChange={(e) => handleChange('type', e.target.value)}
        >
          {types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>
      <div className="ticket-filters__group">
        <label className="ticket-filters__label">Sprint</label>
        <select
          className="ticket-filters__select"
          value={filters.sprint_id || 'all'}
          onChange={(e) => handleChange('sprint_id', e.target.value)}
        >
          <option value="all">all sprints</option>
          {sprints.map((s) => (
            <option key={s.id} value={s.id}>S{s.sprint_number}: {s.name}</option>
          ))}
        </select>
      </div>
      <div className="ticket-filters__group">
        <label className="ticket-filters__label">Epic</label>
        <select
          className="ticket-filters__select"
          value={filters.epic_id || 'all'}
          onChange={(e) => handleChange('epic_id', e.target.value)}
        >
          <option value="all">all epics</option>
          {epics.map((e) => (
            <option key={e.id} value={e.id}>{e.name}</option>
          ))}
        </select>
      </div>
      <div className="ticket-filters__group">
        <label className="ticket-filters__label">Agent</label>
        <select
          className="ticket-filters__select"
          value={filters.agent_id || 'all'}
          onChange={(e) => handleChange('agent_id', e.target.value)}
        >
          <option value="all">all agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

export default TicketFilters;
