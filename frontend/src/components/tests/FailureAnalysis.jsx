// Path: src/components/tests/FailureAnalysis.jsx
// File: FailureAnalysis.jsx
// Created: 2026-03-29
// Purpose: Multi-view failure analysis dashboard with summary, by-type/agent/sprint charts, trends, logging form, and pending review
// Caller: ProjectTestsPage.jsx
// Callees: react (useState, useEffect, useCallback), useStore, api/failureRecords (getFailureSummary, getFailureRecords, createFailureRecord, updateFailureRecord), AsciiChart, tests.css, charts.css
// Data In: projectId prop
// Data Out: default export FailureAnalysis component
// Last Modified: 2026-03-29

import { useState, useEffect, useCallback } from 'react';
import useStore from '../../store/useStore';
import { getFailureSummary, getFailureRecords, createFailureRecord, updateFailureRecord } from '../../api/failureRecords';
import AsciiChart from '../common/AsciiChart';
import '../../styles/tests.css';
import '../../styles/charts.css';

const FAILURE_TYPES = {
  context_degradation: 'Context Degradation',
  spec_drift: 'Spec Drift',
  sycophantic_confirmation: 'Sycophantic Confirmation',
  tool_selection_error: 'Tool Selection Error',
  cascading_failure: 'Cascading Failure',
  silent_failure: 'Silent Failure',
  integration_failure: 'Integration Failure',
};

const FAILURE_TYPE_OPTIONS = Object.entries(FAILURE_TYPES).map(([value, label]) => ({
  value,
  label,
}));

const SEVERITY_OPTIONS = ['low', 'medium', 'high', 'critical'];

const SPARKLINE_CHARS = '\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588';
const MAX_BAR_HEIGHT = 8;

function sparkline(values) {
  if (values.length === 0) return '';
  const max = Math.max(...values, 1);
  return values
    .map((v) => {
      const idx = Math.round((v / max) * 7);
      return SPARKLINE_CHARS[idx];
    })
    .join('');
}

// --- Sub-views ---

function SummaryView({ summary }) {
  if (!summary) return <div className="empty-state">No failure data</div>;

  return (
    <div className="fa-summary">
      <div className="fa-summary__cards">
        <div className="fa-summary__card">
          <div className="fa-summary__card-value">{summary.total_failures || 0}</div>
          <div className="fa-summary__card-label">Total Failures</div>
        </div>
        <div className="fa-summary__card">
          <div className="fa-summary__card-value fa-summary__card-value--orange">
            {summary.most_common_type ? FAILURE_TYPES[summary.most_common_type] || summary.most_common_type : '--'}
          </div>
          <div className="fa-summary__card-label">Most Common Type</div>
        </div>
        <div className="fa-summary__card">
          <div className="fa-summary__card-value fa-summary__card-value--blue">
            {summary.worst_agent || '--'}
          </div>
          <div className="fa-summary__card-label">Most Failures (Agent)</div>
        </div>
        <div className="fa-summary__card">
          <div className="fa-summary__card-value">
            {summary.open_count || 0}
            <span className="fa-summary__card-sub"> open</span>
            {' / '}
            {summary.resolved_count || 0}
            <span className="fa-summary__card-sub"> resolved</span>
          </div>
          <div className="fa-summary__card-label">Status</div>
        </div>
        <div className="fa-summary__card">
          <div className={`fa-summary__card-value ${summary.trend === 'up' ? 'fa-summary__card-value--red' : summary.trend === 'down' ? 'fa-summary__card-value--green' : ''}`}>
            {summary.trend === 'up' ? '\u25B2 Increasing' : summary.trend === 'down' ? '\u25BC Decreasing' : '\u2014 Stable'}
          </div>
          <div className="fa-summary__card-label">Trend vs Previous Sprint</div>
        </div>
      </div>
    </div>
  );
}

function ByTypeView({ records }) {
  const counts = {};
  records.forEach((r) => {
    const type = r.failure_type || 'unknown';
    counts[type] = (counts[type] || 0) + 1;
  });

  const data = Object.entries(counts)
    .map(([type, count]) => ({
      label: FAILURE_TYPES[type] || type,
      value: count,
    }))
    .sort((a, b) => b.value - a.value);

  if (data.length === 0) return <div className="empty-state">No failures recorded</div>;

  return <AsciiChart title="Failures by Type" data={data} maxBarWidth={30} colorClass="orange" />;
}

function ByAgentView({ records, agents }) {
  const agentCounts = {};
  records.forEach((r) => {
    const aid = r.agent_id;
    if (!agentCounts[aid]) agentCounts[aid] = { total: 0, types: {} };
    agentCounts[aid].total += 1;
    const t = r.failure_type || 'unknown';
    agentCounts[aid].types[t] = (agentCounts[aid].types[t] || 0) + 1;
  });

  const rows = Object.entries(agentCounts)
    .map(([aid, data]) => {
      const agent = agents.find((a) => a.id === Number(aid));
      const mostCommon = Object.entries(data.types).sort((a, b) => b[1] - a[1])[0];
      return {
        name: agent ? `${agent.name}/${agent.role}` : `agent ${aid}`,
        total: data.total,
        mostCommonType: mostCommon ? (FAILURE_TYPES[mostCommon[0]] || mostCommon[0]) : '--',
      };
    })
    .sort((a, b) => b.total - a.total);

  if (rows.length === 0) return <div className="empty-state">No failures recorded</div>;

  return (
    <div className="ascii-chart">
      <div className="ascii-chart__title">Failures by Agent</div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Failures</th>
            <th>Most Common Type</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>{row.name}</td>
              <td>{row.total}</td>
              <td>{row.mostCommonType}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BySprintView({ records, sprints, projectId }) {
  const projectSprints = [...sprints]
    .filter((s) => s.project_id === Number(projectId))
    .sort((a, b) => b.sprint_number - a.sprint_number);

  const sprintCounts = {};
  records.forEach((r) => {
    const sid = r.sprint_id;
    if (sid) sprintCounts[sid] = (sprintCounts[sid] || 0) + 1;
  });

  const data = projectSprints.map((s) => ({
    id: s.id,
    label: `S${s.sprint_number}`,
    value: sprintCounts[s.id] || 0,
  }));

  if (data.length === 0) return <div className="empty-state">No sprint data</div>;

  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="ascii-chart">
      <div className="ascii-chart__title">Failures by Sprint</div>
      <div className="vbar-chart">
        {data.map((item, i) => {
          let filled = Math.round((item.value / maxValue) * MAX_BAR_HEIGHT);
          if (item.value > 0 && filled === 0) filled = 1;
          const empty = MAX_BAR_HEIGHT - filled;
          return (
            <div key={i} className="vbar-chart__col">
              <span className="vbar-chart__value">{item.value}</span>
              <div className="vbar-chart__bar">
                <span className="vbar-chart__empty">{'\u2591\n'.repeat(empty)}</span>
                <span className="vbar-chart__filled vbar-chart__filled--red">{'\u2588\n'.repeat(filled)}</span>
              </div>
              <span className="vbar-chart__label">{item.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TrendsView({ records, sprints, projectId }) {
  const projectSprints = [...sprints]
    .filter((s) => s.project_id === Number(projectId))
    .sort((a, b) => a.sprint_number - b.sprint_number);

  const types = Object.keys(FAILURE_TYPES);

  const trendData = types.map((type) => {
    const values = projectSprints.map((s) => {
      return records.filter((r) => r.sprint_id === s.id && r.failure_type === type).length;
    });

    const recent = values.slice(-2);
    let trend = '\u2014';
    if (recent.length >= 2) {
      if (recent[1] > recent[0]) trend = '\u25B2';
      else if (recent[1] < recent[0]) trend = '\u25BC';
    }

    const hasAny = values.some((v) => v > 0);

    return {
      label: FAILURE_TYPES[type],
      values,
      sparklineStr: sparkline(values),
      trend,
      total: values.reduce((s, v) => s + v, 0),
      hasAny,
    };
  }).filter((d) => d.hasAny);

  if (trendData.length === 0) return <div className="empty-state">No trend data available</div>;

  return (
    <div className="ascii-chart">
      <div className="ascii-chart__title">Failure Trends by Type</div>
      {trendData.map((row, i) => (
        <div key={i} className="fa-trend__row">
          <span className="fa-trend__label">{row.label}</span>
          <span className="sparkline sparkline--orange">{row.sparklineStr}</span>
          <span className={`fa-trend__indicator${row.trend === '\u25B2' ? ' fa-trend__indicator--up' : row.trend === '\u25BC' ? ' fa-trend__indicator--down' : ''}`}>
            {row.trend}
          </span>
          <span className="fa-trend__total">{row.total} total</span>
        </div>
      ))}
    </div>
  );
}

function LogFailureForm({ projectId, onSubmitted }) {
  const tickets = useStore((s) => s.tickets).filter((t) => t.project_id === Number(projectId));
  const agents = useStore((s) => s.agents);
  const projectAgents = useStore((s) => s.projectAgents);
  const activeAgentIds = new Set(
    projectAgents.filter((pa) => pa.project_id === Number(projectId)).map((pa) => pa.agent_id)
  );
  const projectAgentList = agents.filter((a) => activeAgentIds.has(a.id));

  const [form, setForm] = useState({
    ticket_id: '',
    agent_id: '',
    failure_type: '',
    severity: 'medium',
    notes: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.ticket_id || !form.agent_id || !form.failure_type) return;
    setSubmitting(true);
    setResult(null);
    try {
      await createFailureRecord({
        project_id: Number(projectId),
        ticket_id: Number(form.ticket_id),
        agent_id: Number(form.agent_id),
        failure_type: form.failure_type,
        severity: form.severity,
        notes: form.notes || null,
      });
      setResult('done');
      setForm({ ticket_id: '', agent_id: '', failure_type: '', severity: 'medium', notes: '' });
      onSubmitted();
    } catch {
      setResult('error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ascii-chart">
      <div className="ascii-chart__title">Log Failure</div>
      <form className="fa-form" onSubmit={handleSubmit}>
        <div className="fa-form__row">
          <label className="fa-form__label">Ticket</label>
          <select
            className="fa-form__select"
            value={form.ticket_id}
            onChange={(e) => setForm({ ...form, ticket_id: e.target.value })}
          >
            <option value="">-- select ticket --</option>
            {tickets.map((t) => (
              <option key={t.id} value={t.id}>{t.key || `#${t.id}`}: {t.title}</option>
            ))}
          </select>
        </div>

        <div className="fa-form__row">
          <label className="fa-form__label">Agent</label>
          <select
            className="fa-form__select"
            value={form.agent_id}
            onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
          >
            <option value="">-- select agent --</option>
            {projectAgentList.map((a) => (
              <option key={a.id} value={a.id}>{a.name}/{a.role}</option>
            ))}
          </select>
        </div>

        <div className="fa-form__row">
          <label className="fa-form__label">Failure Type</label>
          <select
            className="fa-form__select"
            value={form.failure_type}
            onChange={(e) => setForm({ ...form, failure_type: e.target.value })}
          >
            <option value="">-- select type --</option>
            {FAILURE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        <div className="fa-form__row">
          <label className="fa-form__label">Severity</label>
          <select
            className="fa-form__select"
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: e.target.value })}
          >
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="fa-form__row">
          <label className="fa-form__label">Notes</label>
          <textarea
            className="fa-form__textarea"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={3}
            placeholder="What happened? Context, tools involved, root cause..."
          />
        </div>

        <div className="fa-form__actions">
          <button
            className="sync-btn"
            type="submit"
            disabled={submitting || !form.ticket_id || !form.agent_id || !form.failure_type}
          >
            {submitting ? '$ logging...' : '$ log failure'}
          </button>
          {result === 'done' && <span className="sync-btn__status">{'\u2713'} logged</span>}
          {result === 'error' && <span className="sync-btn__status" style={{ color: 'var(--red)' }}>failed</span>}
        </div>
      </form>
    </div>
  );
}

function PendingReviewItem({ record, onSaved }) {
  const [form, setForm] = useState({
    failure_type: record.failure_type === 'TBD' ? '' : (record.failure_type || ''),
    severity: record.severity || 'medium',
    notes: record.notes || '',
    root_cause: record.root_cause || '',
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    if (!form.failure_type) return;
    setSaving(true);
    try {
      await updateFailureRecord(record.id, {
        failure_type: form.failure_type,
        severity: form.severity,
        notes: form.notes || null,
        root_cause: form.root_cause || null,
      });
      onSaved();
    } catch {
      // silent
    } finally {
      setSaving(false);
    }
  };

  const ticket = record.ticket_key || `#${record.ticket_id}`;
  const label = record.failure_type === 'rework' ? 'rework' : 'TBD';

  return (
    <div className="fa-review__item">
      <div className="fa-review__item-header">
        <span className="fa-review__ticket">{ticket}</span>
        <span className="fa-review__badge">[{label}]</span>
        {record.agent_name && <span className="fa-review__agent">{record.agent_name}</span>}
      </div>
      <form className="fa-form" onSubmit={handleSave}>
        <div className="fa-form__row">
          <label className="fa-form__label">Type</label>
          <select
            className="fa-form__select"
            value={form.failure_type}
            onChange={(e) => setForm({ ...form, failure_type: e.target.value })}
          >
            <option value="">-- select type --</option>
            {FAILURE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div className="fa-form__row">
          <label className="fa-form__label">Severity</label>
          <select
            className="fa-form__select"
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: e.target.value })}
          >
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="fa-form__row">
          <label className="fa-form__label">Notes</label>
          <textarea
            className="fa-form__textarea"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={2}
            placeholder="What happened?"
          />
        </div>
        <div className="fa-form__row">
          <label className="fa-form__label">Root Cause</label>
          <textarea
            className="fa-form__textarea"
            value={form.root_cause}
            onChange={(e) => setForm({ ...form, root_cause: e.target.value })}
            rows={2}
            placeholder="Why did it happen?"
          />
        </div>
        <div className="fa-form__actions">
          <button
            className="sync-btn"
            type="submit"
            disabled={saving || !form.failure_type}
          >
            {saving ? '$ saving...' : '$ save'}
          </button>
        </div>
      </form>
    </div>
  );
}

function PendingReview({ records, onSaved }) {
  const pending = records.filter(
    (r) => r.failure_type === 'TBD' || r.failure_type === 'rework'
  );

  if (pending.length === 0) return null;

  return (
    <div className="ascii-chart fa-review">
      <div className="ascii-chart__title">
        Pending Review
        <span className="fa-review__count">{pending.length}</span>
      </div>
      {pending.map((r) => (
        <PendingReviewItem key={r.id} record={r} onSaved={onSaved} />
      ))}
    </div>
  );
}

// --- Main Component ---

const VIEWS = [
  { key: 'summary', label: 'summary' },
  { key: 'by-type', label: 'by type' },
  { key: 'by-agent', label: 'by agent' },
  { key: 'by-sprint', label: 'by sprint' },
  { key: 'trends', label: 'trends' },
  { key: 'log', label: 'log' },
];

function FailureAnalysis({ projectId }) {
  const [view, setView] = useState('summary');
  const [summary, setSummary] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const agents = useStore((s) => s.agents);
  const sprints = useStore((s) => s.sprints);

  const fetchData = useCallback(async () => {
    try {
      const [summaryData, recordsData] = await Promise.all([
        getFailureSummary(projectId),
        getFailureRecords(projectId),
      ]);
      setSummary(summaryData);
      setRecords(recordsData);
    } catch {
      // endpoints may not exist yet
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) return null;

  return (
    <div className="fa">
      <PendingReview records={records} onSaved={fetchData} />
      <div className="fa__view-bar">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            className={`fa__view-btn${view === v.key ? ' fa__view-btn--active' : ''}`}
            onClick={() => setView(v.key)}
          >
            [{v.label}]
          </button>
        ))}
      </div>

      {view === 'summary' && <SummaryView summary={summary} />}
      {view === 'by-type' && <ByTypeView records={records} />}
      {view === 'by-agent' && <ByAgentView records={records} agents={agents} />}
      {view === 'by-sprint' && <BySprintView records={records} sprints={sprints} projectId={projectId} />}
      {view === 'trends' && <TrendsView records={records} sprints={sprints} projectId={projectId} />}
      {view === 'log' && <LogFailureForm projectId={projectId} onSubmitted={fetchData} />}
    </div>
  );
}

export default FailureAnalysis;
