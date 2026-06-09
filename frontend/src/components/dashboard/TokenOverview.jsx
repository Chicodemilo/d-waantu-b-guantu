// Path: src/components/dashboard/TokenOverview.jsx
// File: TokenOverview.jsx
// Created: 2026-03-29
// Purpose: Dashboard section with three AsciiCharts showing token usage by project, by agent, and overhead breakdown
// Caller: DashboardPage.jsx
// Callees: react (useState, useEffect), useStore, services/tracking, utils/format, AsciiChart, dashboard.css
// Data In: projects from store; tracking summaries from API
// Data Out: default export TokenOverview component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTokens } from '../../utils/format';
import AsciiChart from '../common/AsciiChart';
import '../../styles/dashboard.css';

function TokenOverview() {
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
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

  const projectData = projects.map((p) => {
    const summary = summaries[p.id];
    const total = summary ? (summary.project_total.tokens || 0) + (summary.project_total.overhead_tokens || 0) : 0;
    return {
      label: p.prefix,
      value: total,
      displayValue: formatTokens(total),
    };
  });

  const agentData = projects.flatMap((p) => {
    const summary = summaries[p.id];
    if (!summary) return [];
    return (summary.per_agent || [])
      .filter((a) => a.role !== 'team-lead' && a.role !== 'pm')
      .map((a) => ({
        label: `${a.name}/${a.role}`,
        value: a.tokens || 0,
        displayValue: formatTokens(a.tokens || 0),
      }));
  });

  const overheadData = projects.flatMap((p) => {
    const summary = summaries[p.id];
    if (!summary) return [];
    return (summary.per_agent || [])
      .filter((a) => a.role === 'team-lead' || a.role === 'pm')
      .map((a) => ({
        label: `${a.name}/${a.role}`,
        value: a.tokens || 0,
        displayValue: formatTokens(a.tokens || 0),
      }));
  });

  return (
    <div className="token-overview">
      <AsciiChart title="Tokens by Project" tooltip="Total tokens for all agents on the project, includes team lead, PM, and worker agents." data={projectData} colorClass="gradient" />
      <AsciiChart title="Tokens by Agent" tooltip="Tokens consumed by each agent across their assigned tickets." data={agentData} colorClass="blue" />
      <AsciiChart title="Overhead Tokens" tooltip="Tokens spent by the Team Lead (TL) and Project Manager (PM) on coordination — not tied to specific tickets. Tracked separately per project." data={overheadData} />
    </div>
  );
}

export default TokenOverview;
