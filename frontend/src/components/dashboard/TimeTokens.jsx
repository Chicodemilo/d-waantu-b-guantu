// Path: src/components/dashboard/TimeTokens.jsx
// File: TimeTokens.jsx
// Created: 2026-03-30
// Purpose: Tabbed "Time & Tokens" section with data tables (by project, by agent, overhead) and expandable per-ticket breakdowns
// Caller: DashboardPage.jsx, ProjectPage.jsx
// Callees: react (useState, useEffect), useStore, services/tracking, utils/format, dashboard.css
// Data In: Optional projectId prop (single project mode); projects from store; tracking summaries from API
// Data Out: default export TimeTokens component
// Last Modified: 2026-03-30

import { useState, useEffect } from 'react';
import useStore from '../../store/useStore';
import { getTrackingSummary } from '../../services/tracking';
import { formatTokens, formatTime } from '../../utils/format';
import '../../styles/dashboard.css';

function TTSection({ title, tooltip, columns, rows, tickets }) {
  const [expanded, setExpanded] = useState(null);

  return (
    <div className="tt-section">
      <div className="tt-section__title">
        {title}
        {tooltip && (
          <span className="tooltip-trigger">?<span className="tooltip-content">{tooltip}</span></span>
        )}
      </div>
      <table className="tt-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} className={col.className || ''}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const isOpen = expanded === i;
            const itemTickets = tickets ? tickets.filter(row.ticketFilter) : [];
            const hasTickets = itemTickets.length > 0;
            return (
              <tr key={i} className="tt-table__group">
                <td colSpan={columns.length} className="tt-table__group-cell">
                  <div
                    className={`tt-table__row ${hasTickets ? 'tt-table__row--expandable' : ''}`}
                    onClick={() => { if (hasTickets) setExpanded(isOpen ? null : i); }}
                  >
                    {hasTickets && (
                      <span className={`tt-caret ${isOpen ? 'tt-caret--open' : ''}`}>&#9654;</span>
                    )}
                    <span className="tt-table__name">{row.label}</span>
                    <span className="tt-table__tokens">{row.tokensDisplay}</span>
                    <span className="tt-table__time">{row.timeDisplay}</span>
                  </div>
                  {isOpen && itemTickets.length > 0 && (
                    <div className="tt-breakdown">
                      {itemTickets.map((t) => (
                        <div key={t.ticket_key || t.id} className="tt-breakdown__row">
                          <span className="tt-breakdown__key">{t.ticket_key}</span>
                          <span className="tt-breakdown__title">{t.title}</span>
                          <span className="tt-breakdown__tokens">{formatTokens(t.tokens_used || 0)}</span>
                          <span className="tt-breakdown__time">{formatTime(t.time_spent_seconds || 0)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr><td colSpan={columns.length} className="tt-table__empty">&mdash;</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function TimeTokens({ projectId }) {
  const allProjects = useStore((s) => s.projects).filter((p) => p.status === 'active');
  const projects = projectId
    ? allProjects.filter((p) => p.id === Number(projectId))
    : allProjects;
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

  const columns = [
    { key: 'name', label: projectId ? 'Agent / Role' : 'Name' },
    { key: 'tokens', label: 'Tokens', className: 'tt-table__col-right' },
    { key: 'time', label: 'Time', className: 'tt-table__col-right' },
  ];

  const projectRows = projects.map((p) => {
    const summary = summaries[p.id];
    const tokens = summary ? (summary.project_total.tokens || 0) + (summary.project_total.overhead_tokens || 0) : 0;
    const time = summary ? (summary.project_total.time || 0) : 0;
    return {
      label: p.prefix,
      tokensDisplay: formatTokens(tokens),
      timeDisplay: formatTime(time),
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
  const agentRows = Object.values(agentMap).map((a) => ({
    label: a.label,
    tokensDisplay: formatTokens(a.tokens),
    timeDisplay: formatTime(a.time),
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
  const overheadRows = Object.values(overheadMap).map((a) => ({
    label: a.label,
    tokensDisplay: formatTokens(a.tokens),
    timeDisplay: formatTime(a.time),
    ticketFilter: (t) => t.assigned_agent_id === a.agent_id,
  }));

  return (
    <div className="time-tokens">
      <div className="time-tokens__body">
        {!projectId && (
          <TTSection
            title="By Project"
            tooltip="Total tokens and time across all agents on the project."
            columns={columns}
            rows={projectRows}
            tickets={allTickets}
          />
        )}
        <TTSection
          title="By Agent"
          tooltip="Worker agents — tokens and time consumed across their assigned tickets."
          columns={columns}
          rows={agentRows}
          tickets={allTickets}
        />
        <TTSection
          title="Overhead"
          tooltip="Team Lead and PM coordination — not tied to specific tickets."
          columns={columns}
          rows={overheadRows}
          tickets={allTickets}
        />
      </div>
    </div>
  );
}

export default TimeTokens;
