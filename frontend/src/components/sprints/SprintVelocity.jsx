// Path: src/components/sprints/SprintVelocity.jsx
// File: SprintVelocity.jsx
// Created: 2026-03-29
// Purpose: Renders vertical bar chart showing tickets completed per sprint (velocity)
// Caller: SprintPage.jsx, ProjectPage.jsx
// Callees: react-router-dom (Link), useStore, charts.css
// Data In: projectId prop
// Data Out: default export SprintVelocity component
// Last Modified: 2026-03-29

import { Link } from 'react-router-dom';
import useStore from '../../store/useStore';
import '../../styles/charts.css';

const MAX_BAR_HEIGHT = 10;

function SprintVelocity({ projectId }) {
  const sprints = useStore((s) => s.getSprintsByProject(projectId));
  const tickets = useStore((s) => s.tickets);

  const data = [...sprints]
    .sort((a, b) => b.sprint_number - a.sprint_number)
    .map((sprint) => {
      const sprintTickets = tickets.filter((t) => t.sprint_id === sprint.id);
      const done = sprintTickets.filter((t) => t.status === 'done').length;
      return {
        id: sprint.id,
        label: `S${sprint.sprint_number}`,
        value: done,
        total: sprintTickets.length,
      };
    });

  if (data.length === 0) return null;

  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="ascii-chart">
      <div className="ascii-chart__title">Sprint Velocity (tickets completed)</div>
      <div className="vbar-chart">
        {data.map((item, i) => {
          let filled = Math.round((item.value / maxValue) * MAX_BAR_HEIGHT);
          if (item.value > 0 && filled === 0) filled = 1;
          const empty = MAX_BAR_HEIGHT - filled;
          return (
            <Link key={i} to={`/projects/${projectId}/sprints/${item.id}`} className="vbar-chart__col vbar-chart__col--link">
              <span className="vbar-chart__value">{item.value}</span>
              <div className="vbar-chart__bar">
                <span className="vbar-chart__empty">{'░\n'.repeat(empty)}</span>
                <span className="vbar-chart__filled">{'█\n'.repeat(filled)}</span>
              </div>
              <span className="vbar-chart__label">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default SprintVelocity;
