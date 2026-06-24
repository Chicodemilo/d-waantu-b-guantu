// Path: src/components/agents/AgentList.jsx
// File: AgentList.jsx
// Created: 2026-03-29
// Purpose: Renders agents across active projects as a sortable table (DWB-460) with Project/Agent/Role/Rep/Status/Description columns, default sorted by reputation descending, scrollable body under a sticky header
// Caller: DashboardPage.jsx
// Callees: react (useState, useEffect, useMemo), react-router-dom (useNavigate), useStore, api/scores (getProjectScores), agents.css
// Data In: None (reads agents, projectAgents, projects from store; fetches per-project scores)
// Data Out: default export AgentList component
// Last Modified: 2026-06-24

import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import useStore from '../../store/useStore';
import { getProjectScores } from '../../api/scores';
import '../../styles/agents.css';

function AgentList() {
  const navigate = useNavigate();
  const agents = useStore((s) => s.agents);
  const projectAgents = useStore((s) => s.projectAgents);
  const projects = useStore((s) => s.projects).filter((p) => p.status === 'active');

  const [sort, setSort] = useState('rep');
  const [order, setOrder] = useState('desc');

  const entries = projectAgents.map((pa) => {
    const agent = agents.find((a) => a.id === pa.agent_id);
    const project = projects.find((p) => p.id === pa.project_id);
    if (!agent || !project) return null;
    return { key: `${pa.project_id}-${pa.agent_id}`, agent, project };
  }).filter(Boolean);

  // Reputation is per-(agent, project). Each row is one project+agent pairing,
  // so fetch each shown project's leaderboard once and key reputation by
  // `${projectId}-${agentId}`. Defaults to 0 when the agent is absent.
  const [repByKey, setRepByKey] = useState({});
  const projectIdsKey = [...new Set(entries.map((e) => e.project.id))].sort((a, b) => a - b).join(',');

  useEffect(() => {
    let cancelled = false;
    const projectIds = projectIdsKey ? projectIdsKey.split(',').map(Number) : [];
    if (projectIds.length === 0) {
      setRepByKey({});
      return;
    }
    Promise.all(
      projectIds.map((pid) =>
        getProjectScores(pid)
          .then((rows) => ({ pid, rows: Array.isArray(rows) ? rows : [] }))
          .catch(() => ({ pid, rows: [] }))
      )
    ).then((results) => {
      if (cancelled) return;
      const map = {};
      results.forEach(({ pid, rows }) => {
        rows.forEach((r) => { map[`${pid}-${r.agent_id}`] = r.reputation; });
      });
      setRepByKey(map);
    });
    return () => { cancelled = true; };
  }, [projectIdsKey]);

  const COLUMNS = [
    { key: 'project',     label: 'Project',     align: 'left'  },
    { key: 'agent',       label: 'Agent',       align: 'left'  },
    { key: 'role',        label: 'Role',        align: 'left'  },
    { key: 'rep',         label: 'Rep',         align: 'right' },
    { key: 'status',      label: 'Status',      align: 'left'  },
    { key: 'description', label: 'Description', align: 'left'  },
  ];

  const repOf = (e) => repByKey[`${e.project.id}-${e.agent.id}`] ?? 0;

  const rows = useMemo(() => {
    const valueFor = (e) => {
      switch (sort) {
        case 'project':     return e.project.prefix.toLowerCase();
        case 'agent':       return e.agent.name.toLowerCase();
        case 'role':        return (e.agent.role || '').toLowerCase();
        case 'rep':         return repOf(e);
        case 'status':      return e.agent.is_active ? 1 : 0;
        case 'description': return (e.agent.description || '').toLowerCase();
        default:            return 0;
      }
    };
    const dir = order === 'asc' ? 1 : -1;
    return [...entries].sort((a, b) => {
      const va = valueFor(a);
      const vb = valueFor(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      // Stable tiebreak: name ascending so equal-rep rows keep a fixed order.
      return a.agent.name.toLowerCase().localeCompare(b.agent.name.toLowerCase());
    });
  }, [entries, sort, order, repByKey]);

  const handleSort = (colKey) => {
    if (sort === colKey) {
      setOrder(order === 'asc' ? 'desc' : 'asc');
    } else {
      setSort(colKey);
      // Rep defaults to high-to-low; text columns default to A-to-Z.
      setOrder(colKey === 'rep' ? 'desc' : 'asc');
    }
  };

  if (entries.length === 0) {
    return <div className="empty-state">No agents on active projects yet.</div>;
  }

  return (
    <div className="agent-table-scroll">
      <table className="data-table agent-table">
        <thead>
          <tr>
            {COLUMNS.map((col) => {
              const isSorted = sort === col.key;
              const arrow = isSorted ? (order === 'asc' ? ' ^' : ' v') : '';
              return (
                <th
                  key={col.key}
                  className={`${isSorted ? 'th--sorted ' : ''}agent-table__th--${col.align}`}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}{arrow}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ key, agent, project }) => (
            <tr
              key={key}
              className="data-table__row--clickable"
              onClick={() => navigate(`/projects/${project.id}/agents/${agent.id}`)}
            >
              <td className="agent-table__project">{project.prefix.toLowerCase()}</td>
              <td className="agent-table__agent">{agent.name}</td>
              <td className="agent-table__role">{agent.role}</td>
              <td className="agent-table__rep">{repByKey[`${project.id}-${agent.id}`] ?? 0}</td>
              <td>
                <span className="agent-table__status">
                  <span
                    className={`agent-card__status-dot${agent.is_active ? '' : ' agent-card__status-dot--inactive'}`}
                  />
                  {agent.is_active ? 'active' : 'inactive'}
                </span>
              </td>
              <td className="agent-table__desc">{agent.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default AgentList;
