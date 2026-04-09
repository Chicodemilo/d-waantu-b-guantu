// Path: src/pages/TestResultsPage.jsx
// File: TestResultsPage.jsx
// Created: 2026-03-29
// Purpose: Global test results view with run system tests button, test run list with detail drill-down, and test coverage
// Caller: App.jsx (route: /tests, /tests/:runId)
// Callees: react, react-router-dom, ../store/useStore, ../api/system, ../components/common/StatusBadge, ../components/common/TerminalOutput, ../components/tests/TestCoverage, ../styles/tests.css
// Data In: Route param (runId), testRuns from Zustand store
// Data Out: Default export TestResultsPage component
// Last Modified: 2026-04-09

import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import { runSystemTests } from '../api/system';
import StatusBadge from '../components/common/StatusBadge';
import TerminalOutput from '../components/common/TerminalOutput';
import TestCoverage from '../components/tests/TestCoverage';
import '../styles/tests.css';

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function TestRunDetail({ run }) {
  const details = run.details || {};
  const tests = details.tests || [];
  const [outcomeFilter, setOutcomeFilter] = useState(null);

  const toggleFilter = (outcome) => {
    setOutcomeFilter((prev) => (prev === outcome ? null : outcome));
  };

  const filtered = outcomeFilter
    ? tests.filter((t) => t.outcome === outcomeFilter)
    : tests;

  return (
    <div className="test-detail">
      <div className="test-detail__header">
        <span>{run.suite}</span>
        <span>{formatTime(run.run_at)}</span>
        <StatusBadge status={run.status} />
        <span className="test-run-row__triggered">
          {run.triggered_by}{run.triggered_context ? ` \u2014 ${run.triggered_context}` : ''}
        </span>
      </div>
      <div className="test-detail__summary">
        <button
          className={`test-filter-btn test-run-row__passed${outcomeFilter === 'passed' ? ' test-filter-btn--active' : ''}`}
          onClick={() => toggleFilter('passed')}
        >
          {run.passed} passed
        </button>
        <button
          className={`test-filter-btn test-run-row__failed${outcomeFilter === 'failed' ? ' test-filter-btn--active' : ''}`}
          onClick={() => toggleFilter('failed')}
        >
          {run.failed} failed
        </button>
        {run.skipped > 0 && <span>{run.skipped} skipped</span>}
      </div>
      {filtered.map((t, i) => (
        <div key={i}>
          <div className="test-case">
            <span className={t.outcome === 'passed' ? 'test-case__icon--pass' : 'test-case__icon--fail'}>
              {t.outcome === 'passed' ? '\u2713' : '\u2717'}
            </span>
            <span className="test-case__name">{t.nodeid}</span>
            {t.duration != null && (
              <span className="test-case__duration">{Math.round(t.duration * 1000)}ms</span>
            )}
          </div>
          {t.message && <div className="test-case__error">{t.message}</div>}
        </div>
      ))}
      {tests.length === 0 && (
        <div className="empty-state">No test case details available</div>
      )}
    </div>
  );
}

function TestResultsPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const testRuns = useStore((s) => s.testRuns);
  const [selectedId, setSelectedId] = useState(null);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [expandedRunId, setExpandedRunId] = useState(null);
  const [liveOutput, setLiveOutput] = useState(null);

  const handleRunTests = async () => {
    setRunning(true);
    setRunResult(null);
    setLiveOutput(null);
    try {
      const result = await runSystemTests();
      setRunResult(result);
      setLiveOutput(result.stdout_tail || null);
    } catch {
      setRunResult({ error: true });
    } finally {
      setRunning(false);
    }
  };

  const activeId = runId ? Number(runId) : selectedId;
  const selectedRun = activeId ? testRuns.find((r) => r.id === activeId) : null;

  if (selectedRun) {
    return (
      <div>
        <div className="page-title">
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              if (runId) {
                navigate('/tests');
              } else {
                setSelectedId(null);
              }
            }}
          >
            &larr; Back to test runs
          </a>
          <span>Test Run #{selectedRun.id}</span>
        </div>
        <TestRunDetail run={selectedRun} />
      </div>
    );
  }

  const sorted = [...testRuns].sort(
    (a, b) => new Date(b.run_at || 0) - new Date(a.run_at || 0)
  );

  return (
    <div>
      <div className="page-title">Test Results</div>
      <div className="test-actions">
        <button
          className="sync-btn"
          onClick={handleRunTests}
          disabled={running}
        >
          {running ? '$ running...' : '$ run system tests'}
        </button>
        {runResult && !runResult.error && (
          <span className="sync-btn__status">
            {'\u2713'} {runResult.passed || 0} passed, {runResult.failed || 0} failed ({runResult.total || 0} total)
          </span>
        )}
        {runResult?.error && (
          <span className="sync-btn__status" style={{ color: 'var(--red)' }}>test run failed</span>
        )}
      </div>
      <TerminalOutput
        output={liveOutput}
        isOpen={running || liveOutput !== null}
        isLoading={running}
      />
      {sorted.length === 0 ? (
        <div className="test-empty-prompt">
          <div className="test-empty-prompt__text">No test runs found &mdash; run system tests to verify your installation.</div>
          <button
            className="sync-btn"
            onClick={handleRunTests}
            disabled={running}
          >
            {running ? '$ running...' : '$ run system tests'}
          </button>
        </div>
      ) : (
        <div className="test-runs test-runs--expandable">
          {sorted.map((run) => (
            <div key={run.id}>
              <div
                className={`test-run-row test-run-row--clickable${expandedRunId === run.id ? ' test-run-row--expanded' : ''}`}
                onClick={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
              >
                <span
                  className={`test-run-row__expand${expandedRunId === run.id ? ' test-run-row__expand--open' : ''}`}
                >
                  {expandedRunId === run.id ? 'v' : '>'}
                </span>
                <span className="test-run-row__timestamp">
                  {formatTime(run.run_at)}
                </span>
                <button
                  className="test-run-row__detail-link"
                  onClick={(e) => { e.stopPropagation(); setSelectedId(run.id); }}
                >
                  {run.suite}
                </button>
                <span className="test-run-row__passed">{run.passed} pass</span>
                <span className="test-run-row__failed">{run.failed} fail</span>
                <StatusBadge status={run.status} />
                <span className="test-run-row__triggered">
                  {run.triggered_by}{run.triggered_context ? ` \u2014 ${run.triggered_context}` : ''}
                </span>
              </div>
              {expandedRunId === run.id && (
                <TerminalOutput
                  output={run.details?.raw_output_tail}
                  isOpen={true}
                />
              )}
            </div>
          ))}
        </div>
      )}
      <TestCoverage />
    </div>
  );
}

export default TestResultsPage;
