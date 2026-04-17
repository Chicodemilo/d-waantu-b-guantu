// Path: src/components/dashboard/CrossProjectSummary.jsx
// File: CrossProjectSummary.jsx
// Created: 2026-03-29
// Purpose: Dashboard summary panels showing aggregate counts and token/time totals across active projects
// Caller: DashboardPage.jsx
// Callees: react (useState, useEffect), useStore, services/tracking, utils/format, dashboard.css
// Data In: projects, tickets, alerts from store; tracking summaries from API
// Data Out: default export CrossProjectSummary component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTokens, formatTime } from '../../utils/format';
import '../../styles/dashboard.css';

function CrossProjectSummary() {
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const tickets = useStore((s) => s.tickets).filter((t) =>
    projects.some((p) => p.id === t.project_id)
  );
  const alerts = useStore((s) => s.alerts).filter(
    (a) => a.status === 'open' && projects.some((p) => p.id === a.project_id)
  );
  const [summaries, setSummaries] = useState({});

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      projects.map((p) =>
        getTrackingSummary(p.id).then((data) => ({ id: p.id, data }))
      )
    )
      .then((results) => {
        if (cancelled) return;
        const map = {};
        for (const r of results) map[r.id] = r.data;
        setSummaries(map);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [projects.map((p) => p.id).join(',')]);

  let totalTokens = 0;
  let totalTime = 0;
  for (const p of projects) {
    const s = summaries[p.id];
    if (s) {
      totalTokens += (s.project_total.tokens || 0) + (s.project_total.overhead_tokens || 0);
      totalTime += s.project_total.time_seconds || 0;
    }
  }

  const panels = [
    { label: 'Projects', value: projects.length },
    { label: 'Total Tickets', value: tickets.length },
    { label: 'Completed', value: tickets.filter((t) => t.status === 'done').length, className: '' },
    { label: 'In Progress', value: tickets.filter((t) => t.status === 'in_progress').length, className: 'summary-panel__value--orange' },
    { label: 'Tokens', value: formatTokens(totalTokens), className: 'summary-panel__value--blue' },
    { label: 'Time', value: formatTime(totalTime), className: '' },
    { label: 'Open Alerts', value: alerts.length, className: 'summary-panel__value--blue' },
  ];

  return (
    <div className="cross-project-summary">
      {panels.map((p) => (
        <div key={p.label} className="summary-panel">
          <div className={`summary-panel__value ${p.className || ''}`}>
            {p.value}
          </div>
          <div className="summary-panel__label">{p.label}</div>
        </div>
      ))}
    </div>
  );
}

export default CrossProjectSummary;
