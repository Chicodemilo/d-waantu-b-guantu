// Path: src/pages/TestResultsPage.jsx
// File: TestResultsPage.jsx
// Created: 2026-03-29
// Purpose: Global test results view listing all test runs with detail drill-down and test coverage display
// Caller: App.jsx (route: /tests, /tests/:runId)
// Callees: react, react-router-dom, ../store/useStore, ../components/common/StatusBadge, ../components/tests/TestCoverage, ../styles/tests.css
// Data In: Route param (runId), testRuns from Zustand store
// Data Out: Default export TestResultsPage component
// Last Modified: 2026-03-29

import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import StatusBadge from '../components/common/StatusBadge';
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
      <div className="test-runs">
        {sorted.map((run) => (
          <div
            key={run.id}
            className="test-run-row"
            onClick={() => setSelectedId(run.id)}
          >
            <span className="test-run-row__timestamp">
              {formatTime(run.run_at)}
            </span>
            <span className="test-run-row__suite">{run.suite}</span>
            <span className="test-run-row__passed">{run.passed} pass</span>
            <span className="test-run-row__failed">{run.failed} fail</span>
            <StatusBadge status={run.status} />
            <span className="test-run-row__triggered">
              {run.triggered_by}{run.triggered_context ? ` \u2014 ${run.triggered_context}` : ''}
            </span>
          </div>
        ))}
        {sorted.length === 0 && (
          <div className="empty-state">No test runs recorded</div>
        )}
      </div>
      <TestCoverage />
    </div>
  );
}

export default TestResultsPage;
