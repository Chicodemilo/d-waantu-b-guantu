// Path: src/components/dashboard/TimeTokens.jsx
// File: TimeTokens.jsx
// Created: 2026-03-30
// Purpose: Tabbed "Time & Tokens" dashboard section — [tokens] and [time] tabs with by-project, by-agent, overhead bar charts and expandable per-ticket breakdowns
// Caller: DashboardPage.jsx
// Callees: react (useState, useEffect), useStore, services/tracking, utils/format, AsciiChart, dashboard.css
// Data In: projects from store; tracking summaries from API
// Data Out: default export TimeTokens component
// Last Modified: 2026-03-30

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTokens, formatTime } from '../../utils/format';
import AsciiChart from '../common/AsciiChart';
import '../../styles/dashboard.css';

function ExpandableChart({ title, tooltip, data, colorClass, tickets, mode }) {
  const [expanded, setExpanded] = useState(null);

  return (
    <div className="ascii-chart">
      {title && (
        <div className="ascii-chart__title">
          {title}
          {tooltip && (
            <span className="tooltip-trigger">?<span className="tooltip-content">{tooltip}</span></span>
          )}
        </div>
      )}
      {data.map((item, i) => {
        const maxValue = Math.max(...data.map((d) => d.value), 1);
        const maxBarWidth = 54;
        let filled = Math.round((item.value / maxValue) * maxBarWidth);
        if (item.value > 0 && filled === 0) filled = 1;
        const empty = maxBarWidth - filled;
        const isOpen = expanded === i;
        const itemTickets = tickets ? tickets.filter(item.ticketFilter) : [];

        return (
          <div key={i}>
            <div
              className={`ascii-chart__row ${itemTickets.length > 0 ? 'ascii-chart__row--expandable' : ''}`}
              onClick={() => {
                if (itemTickets.length > 0) setExpanded(isOpen ? null : i);
              }}
            >
              {itemTickets.length > 0 && (
                <span className={`tt-caret ${isOpen ? 'tt-caret--open' : ''}`}>&#9654;</span>
              )}
              <span className="ascii-chart__label">{item.label}</span>
              <span className="ascii-chart__track">
                <span className={`ascii-chart__bar${colorClass ? ` ascii-chart__bar--${colorClass}` : ''}`}>
                  {'█'.repeat(filled)}
                </span>
                <span className="ascii-chart__bar-empty">{'░'.repeat(empty)}</span>
              </span>
              <span className="ascii-chart__value">
                {item.displayValue}
              </span>
            </div>
            {isOpen && itemTickets.length > 0 && (
              <div className="tt-breakdown">
                {itemTickets.map((t) => (
                  <div key={t.ticket_key || t.id} className="tt-breakdown__row">
                    <span className="tt-breakdown__key">{t.ticket_key}</span>
                    <span className="tt-breakdown__title">{t.title}</span>
                    <span className="tt-breakdown__value">
                      {mode === 'tokens' ? formatTokens(t.tokens_used || 0) : formatTime(t.time_spent_seconds || 0)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function TimeTokens() {
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const [summaries, setSummaries] = useState({});
  const [tab, setTab] = useState('tokens');

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

  const allTickets = projects.flatMap((p) => {
    const summary = summaries[p.id];
    if (!summary) return [];
    return (summary.per_ticket || []).map((t) => ({ ...t, project_id: p.id, project_prefix: p.prefix }));
  });

  const allAgents = projects.flatMap((p) => {
    const summary = summaries[p.id];
    if (!summary) return [];
    return (summary.per_agent || []).map((a) => ({ ...a, project_id: p.id }));
  });

  const fmt = (val) => tab === 'tokens' ? formatTokens(val) : formatTime(val);
  const valKey = tab === 'tokens' ? 'tokens' : 'time';

  const projectData = projects.map((p) => {
    const summary = summaries[p.id];
    const val = tab === 'tokens'
      ? (summary ? (summary.project_total.tokens || 0) + (summary.project_total.overhead_tokens || 0) : 0)
      : (summary ? (summary.project_total.time || 0) : 0);
    return {
      label: p.prefix,
      value: val,
      displayValue: fmt(val),
      ticketFilter: (t) => t.project_id === p.id,
    };
  });

  const workerAgents = allAgents.filter((a) => a.role !== 'team-lead' && a.role !== 'pm');
  const agentMap = {};
  for (const a of workerAgents) {
    const key = `${a.name}/${a.role}`;
    if (!agentMap[key]) agentMap[key] = { label: key, tokens: 0, time: 0, agent_id: a.agent_id };
    agentMap[key].tokens += (a.tokens || 0);
    agentMap[key].time += (a.time || 0);
  }
  const agentData = Object.values(agentMap).map((a) => ({
    label: a.label,
    value: a[valKey] || 0,
    displayValue: fmt(a[valKey] || 0),
    ticketFilter: (t) => t.assigned_agent_id === a.agent_id,
  }));

  const overheadAgents = allAgents.filter((a) => a.role === 'team-lead' || a.role === 'pm');
  const overheadMap = {};
  for (const a of overheadAgents) {
    const key = `${a.name}/${a.role}`;
    if (!overheadMap[key]) overheadMap[key] = { label: key, tokens: 0, time: 0, agent_id: a.agent_id };
    overheadMap[key].tokens += (a.tokens || 0);
    overheadMap[key].time += (a.time || 0);
  }
  const overheadData = Object.values(overheadMap).map((a) => ({
    label: a.label,
    value: a[valKey] || 0,
    displayValue: fmt(a[valKey] || 0),
    ticketFilter: (t) => t.assigned_agent_id === a.agent_id,
  }));

  return (
    <div className="time-tokens">
      <div className="time-tokens__tabs">
        <button
          className={`time-tokens__tab ${tab === 'tokens' ? 'time-tokens__tab--active' : ''}`}
          onClick={() => setTab('tokens')}
        >
          [tokens]
        </button>
        <button
          className={`time-tokens__tab ${tab === 'time' ? 'time-tokens__tab--active' : ''}`}
          onClick={() => setTab('time')}
        >
          [time]
        </button>
      </div>
      <div className="time-tokens__body">
        <ExpandableChart
          title="By Project"
          tooltip="Total across all agents on the project."
          data={projectData}
          colorClass="orange"
          tickets={allTickets}
          mode={tab}
        />
        <ExpandableChart
          title="By Agent"
          tooltip="Worker agents — tokens or time consumed across their assigned tickets."
          data={agentData}
          colorClass="blue"
          tickets={allTickets}
          mode={tab}
        />
        <ExpandableChart
          title="Overhead"
          tooltip="Team Lead and PM coordination — not tied to specific tickets."
          data={overheadData}
          colorClass=""
          tickets={allTickets}
          mode={tab}
        />
      </div>
    </div>
  );
}

export default TimeTokens;
