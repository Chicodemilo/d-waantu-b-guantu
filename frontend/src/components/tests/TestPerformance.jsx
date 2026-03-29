// Path: src/components/tests/TestPerformance.jsx
// File: TestPerformance.jsx
// Created: 2026-03-29
// Purpose: Displays test performance dashboard with duration bar chart, sparkline trends, summary stats, and per-test drill-down
// Caller: ProjectTestsPage.jsx
// Callees: react (useState, useEffect), api/testResults (getTestPerformance, getProjectTestRuns), tests.css, charts.css
// Data In: projectId prop
// Data Out: default export TestPerformance component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { getTestPerformance, getProjectTestRuns } from '../../api/testResults';
import '../../styles/tests.css';
import '../../styles/charts.css';

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

function SparklineWithTooltips({ runs }) {
  if (runs.length === 0) return null;
  const values = runs.map((r) => r.total_tests || 0);
  const max = Math.max(...values, 1);
  return (
    <span className="sparkline">
      {runs.map((r, i) => {
        const v = r.total_tests || 0;
        const idx = Math.round((v / max) * 7);
        const ch = SPARKLINE_CHARS[idx];
        const d = new Date(r.run_at);
        const label = d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
        return (
          <span key={i} className="sparkline-char">
            {ch}
            <span className="sparkline-char__tip">{v} tests — {label}</span>
          </span>
        );
      })}
    </span>
  );
}

function TestDrillDown({ nodeid, testRuns }) {
  // Find this test's duration across all runs
  const entries = [];
  const sorted = [...testRuns].sort(
    (a, b) => new Date(b.run_at || 0) - new Date(a.run_at || 0)
  );
  for (const run of sorted) {
    const tests = run.details?.tests || [];
    const match = tests.find((t) => t.nodeid === nodeid);
    if (match && match.duration != null) {
      entries.push({
        run_at: run.run_at,
        duration: match.duration,
      });
    }
  }

  if (entries.length === 0) {
    return <div className="test-drill__empty">No history available</div>;
  }

  const durations = entries.map((e) => e.duration);
  const avg = durations.reduce((s, d) => s + d, 0) / durations.length;
  const min = Math.min(...durations);
  const max = Math.max(...durations);
  const latest = durations[0];
  const diff = latest - avg;

  return (
    <div className="test-drill">
      <div className="test-drill__stats">
        <span className="test-drill__stat">
          <span className="test-drill__stat-label">avg:</span>
          <span className="test-drill__stat-value">{Math.round(avg * 1000)}ms</span>
        </span>
        <span className="test-drill__stat">
          <span className="test-drill__stat-label">min:</span>
          <span className="test-drill__stat-value">{Math.round(min * 1000)}ms</span>
        </span>
        <span className="test-drill__stat">
          <span className="test-drill__stat-label">max:</span>
          <span className="test-drill__stat-value">{Math.round(max * 1000)}ms</span>
        </span>
        <span className="test-drill__stat">
          <span className="test-drill__stat-label">diff from avg:</span>
          <span className={`test-drill__stat-value${diff > 0 ? ' test-drill__stat-value--over' : ' test-drill__stat-value--under'}`}>
            {diff > 0 ? '+' : ''}{Math.round(diff * 1000)}ms
          </span>
        </span>
      </div>
      <div className="test-drill__history">
        {entries.map((e, i) => {
          const d = new Date(e.run_at);
          const label = d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
          return (
            <div key={i} className="test-drill__row">
              <span className="test-drill__date">{label}</span>
              <span className="test-drill__duration">{Math.round(e.duration * 1000)}ms</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TestPerformance({ projectId }) {
  const [perf, setPerf] = useState(null);
  const [testRuns, setTestRuns] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedTest, setExpandedTest] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getTestPerformance(),
      getProjectTestRuns(projectId),
    ])
      .then(([perfData, runsData]) => {
        if (cancelled) return;
        // Filter performance data to this project's runs
        const projectRunIds = new Set(runsData.map((r) => r.id));
        const projectPerf = perfData.filter((p) => projectRunIds.has(p.id));
        setPerf(projectPerf);
        // Parse details for slowest tests from latest run
        const parsed = runsData.map((run) => {
          if (!run.details || typeof run.details !== 'string') return run;
          try { return { ...run, details: JSON.parse(run.details) }; }
          catch { return run; }
        });
        setTestRuns(parsed);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return null;
  if (!perf || perf.length === 0) {
    return <div className="empty-state">No performance data available</div>;
  }

  // Sort most recent first for bar chart
  const sorted = [...perf].sort(
    (a, b) => new Date(b.run_at || 0) - new Date(a.run_at || 0)
  );
  const maxDuration = Math.max(...sorted.map((r) => r.duration_seconds || 0), 1);

  // Slowest tests from latest run
  const latestRun = testRuns
    ? [...testRuns].sort((a, b) => new Date(b.run_at || 0) - new Date(a.run_at || 0))[0]
    : null;
  const latestTests = (latestRun?.details?.tests || [])
    .filter((t) => t.duration != null)
    .sort((a, b) => b.duration - a.duration);

  // Test count sparkline (oldest to newest)
  const testCounts = [...sorted].reverse().map((r) => r.total_tests || 0);

  // Per-test average durations across all runs
  const testAvgMap = {};
  if (testRuns) {
    const durationsMap = {};
    for (const run of testRuns) {
      for (const t of run.details?.tests || []) {
        if (t.duration != null) {
          if (!durationsMap[t.nodeid]) durationsMap[t.nodeid] = [];
          durationsMap[t.nodeid].push(t.duration);
        }
      }
    }
    for (const [nodeid, durations] of Object.entries(durationsMap)) {
      testAvgMap[nodeid] = durations.reduce((s, d) => s + d, 0) / durations.length;
    }
  }

  return (
    <div>
      <div className="ascii-chart">
        <div className="ascii-chart__title">Duration Over Time (seconds)</div>
        <div className="vbar-chart">
          {sorted.map((run, i) => {
            let filled = Math.round(((run.duration_seconds || 0) / maxDuration) * MAX_BAR_HEIGHT);
            if (run.duration_seconds > 0 && filled === 0) filled = 1;
            const empty = MAX_BAR_HEIGHT - filled;
            const runDate = new Date(run.run_at);
            const label = `${runDate.getMonth() + 1}/${runDate.getDate()}`;
            return (
              <div key={i} className="vbar-chart__col">
                <span className="vbar-chart__value">{(run.duration_seconds || 0).toFixed(1)}</span>
                <div className="vbar-chart__bar">
                  <span className="vbar-chart__empty">{'\u2591\n'.repeat(empty)}</span>
                  <span className="vbar-chart__filled">{'\u2588\n'.repeat(filled)}</span>
                </div>
                <span className="vbar-chart__label">{label}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="test-perf__row">
        <div className="ascii-chart test-perf__sparkline-panel">
          <div className="ascii-chart__title">Test Count Trend</div>
          <div className="test-perf__sparkline">
            <SparklineWithTooltips runs={[...sorted].reverse()} />
            <span className="test-perf__sparkline-value">{testCounts[testCounts.length - 1] || 0} tests</span>
          </div>
        </div>

        <div className="ascii-chart test-perf__summary-panel">
          <div className="ascii-chart__title">Summary</div>
          <div className="test-perf__stat">
            <span className="test-perf__stat-label">runs:</span>
            <span className="test-perf__stat-value">{sorted.length}</span>
          </div>
          <div className="test-perf__stat">
            <span className="test-perf__stat-label">avg duration:</span>
            <span className="test-perf__stat-value">
              {(sorted.reduce((s, r) => s + (r.duration_seconds || 0), 0) / sorted.length).toFixed(1)}s
            </span>
          </div>
          <div className="test-perf__stat">
            <span className="test-perf__stat-label">latest:</span>
            <span className="test-perf__stat-value">
              {sorted[0] ? `${(sorted[0].duration_seconds || 0).toFixed(1)}s` : '--'}
            </span>
          </div>
        </div>
      </div>

      {latestTests.length > 0 && (
        <div className="ascii-chart">
          <div className="ascii-chart__title">Recent Tests</div>
          <div className="test-perf__table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Test</th>
                <th className="test-perf__duration-col">Duration</th>
                <th className="test-perf__avg-col">Avg</th>
                <th className="test-perf__diff-col">Diff</th>
              </tr>
            </thead>
            <tbody>
              {latestTests.map((t, i) => {
                const avg = testAvgMap[t.nodeid];
                const diff = avg != null ? t.duration - avg : null;
                return (
                  <tr key={i}>
                    <td>
                      <button
                        className="test-drill__trigger"
                        onClick={() => setExpandedTest(expandedTest === t.nodeid ? null : t.nodeid)}
                      >
                        {t.nodeid}
                      </button>
                      {expandedTest === t.nodeid && testRuns && (
                        <TestDrillDown nodeid={t.nodeid} testRuns={testRuns} />
                      )}
                    </td>
                    <td className="test-perf__duration-col">{Math.round(t.duration * 1000)}ms</td>
                    <td className="test-perf__avg-col">{avg != null ? `${Math.round(avg * 1000)}ms` : '--'}</td>
                    <td className="test-perf__diff-col">
                      {diff != null ? `${diff > 0 ? '+' : ''}${Math.round(diff * 1000)}ms` : '--'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default TestPerformance;
