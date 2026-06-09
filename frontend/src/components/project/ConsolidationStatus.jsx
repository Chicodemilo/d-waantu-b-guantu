// Path: src/components/project/ConsolidationStatus.jsx
// File: ConsolidationStatus.jsx
// Created: 2026-06-04
// Purpose: Sprint-close consolidation gate panel — per-agent ack status + over-ceiling owned files. Hidden unless project.force_consolidation is true and there is an active sprint.
// Caller: ProjectPage.jsx
// Callees: react (useState, useEffect), useStore, api/client (get), styles/dashboard.css
// Data In: projectId prop
// Data Out: default export ConsolidationStatus component
// Last Modified: 2026-06-08

import { useEffect, useState } from 'react';
import useStore from '../../store/useStore';
import { get } from '../../api/client';
import '../../styles/dashboard.css';

const POLL_MS = 10000;

const formatTokens = (n) => {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
};

function FileChip({ f }) {
  const cls =
    f.status === 'over'
      ? 'consolidation-status__file--over'
      : 'consolidation-status__file--warning';
  return (
    <span className={`consolidation-status__file ${cls}`}>
      <span className="consolidation-status__file-name">{f.name}</span>
      <span className="consolidation-status__file-count">
        {formatTokens(f.tokens)}/{formatTokens(f.ceiling)}
      </span>
    </span>
  );
}

function AgentRow({ agent }) {
  const ackClass = agent.acked
    ? 'consolidation-status__ack--done'
    : 'consolidation-status__ack--pending';
  const ackLabel = agent.acked ? 'acked' : 'pending';
  const files = agent.owned_over_ceiling_files || [];
  return (
    <div className="consolidation-status__agent">
      <div className="consolidation-status__agent-row">
        <span className="consolidation-status__agent-name">{agent.name}</span>
        <span className="consolidation-status__agent-role">{agent.role}</span>
        <span className={`consolidation-status__ack ${ackClass}`}>{ackLabel}</span>
      </div>
      {files.length > 0 && (
        <div className="consolidation-status__files">
          {files.map((f) => (
            <FileChip key={f.name} f={f} />
          ))}
        </div>
      )}
    </div>
  );
}

function ConsolidationStatus({ projectId }) {
  const project = useStore((s) => s.getProject(projectId));
  const sprints = useStore((s) => s.getSprintsByProject(projectId));

  const sortedSprints = [...sprints].sort((a, b) => b.sprint_number - a.sprint_number);
  const activeSprint = sortedSprints.find((s) => s.status === 'active');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const shouldShow = Boolean(project && project.force_consolidation && activeSprint);

  useEffect(() => {
    if (!shouldShow) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const d = await get(`/projects/${projectId}/consolidation-status`, {
          sprint_id: activeSprint.id,
        });
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchOnce();
    const intervalId = setInterval(fetchOnce, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [shouldShow, projectId, activeSprint?.id]);

  if (!shouldShow) return null;
  if (loading && !data) {
    return (
      <div className="consolidation-status">
        <div className="consolidation-status__header">consolidation gate: loading...</div>
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="consolidation-status">
        <div className="consolidation-status__header consolidation-status__header--pending">
          consolidation gate error: {error}
        </div>
      </div>
    );
  }
  if (!data) return null;

  const agents = data.agents || [];
  const pendingCount = agents.filter((a) => !a.acked).length;
  const total = agents.length;
  const ready = data.gate_satisfied;
  const headerClass = ready
    ? 'consolidation-status__header--ready'
    : 'consolidation-status__header--pending';
  const headerLabel = ready
    ? 'ready to close'
    : `${pendingCount} of ${total} agent${total === 1 ? '' : 's'} pending`;

  return (
    <div className="consolidation-status">
      <div className={`consolidation-status__header ${headerClass}`}>
        <span className="consolidation-status__title">Consolidation Gate</span>
        <span className="consolidation-status__state">{headerLabel}</span>
        <span className="consolidation-status__sprint">
          S{activeSprint.sprint_number}: {activeSprint.name}
        </span>
      </div>
      <div className="consolidation-status__agents">
        {agents.length === 0 ? (
          <div className="consolidation-status__empty">No agents assigned to project.</div>
        ) : (
          agents.map((a) => <AgentRow key={a.agent_id} agent={a} />)
        )}
      </div>
    </div>
  );
}

export default ConsolidationStatus;
