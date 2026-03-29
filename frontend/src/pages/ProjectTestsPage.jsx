// Path: src/pages/ProjectTestsPage.jsx
// File: ProjectTestsPage.jsx
// Created: 2026-03-29
// Purpose: Displays project test runs with detail drill-down, performance tab, and failure analysis tab
// Caller: App.jsx (route: /projects/:id/tests)
// Callees: react, react-router-dom, ../store/useStore, ../api/testResults, ../api/alerts, ../components/common/StatusBadge, ../components/tests/TestPerformance, ../components/tests/FailureAnalysis, ../styles/tests.css
// Data In: Route param (id), project from Zustand store, test runs from API
// Data Out: Default export ProjectTestsPage component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import useStore from '../store/useStore';
import { getProjectTestRuns } from '../api/testResults';
import { requestTestRun } from '../api/alerts';
import StatusBadge from '../components/common/StatusBadge';
import TestPerformance from '../components/tests/TestPerformance';
import FailureAnalysis from '../components/tests/FailureAnalysis';
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

function ProjectTestsPage() {
  const { id } = useParams();
  const project = useStore((s) => s.getProject(id));
  const [testRuns, setTestRuns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);
  const [requestResult, setRequestResult] = useState(null);
  const [activeTab, setActiveTab] = useState('results');

  const handleRunTests = async () => {
    setRequesting(true);
    setRequestResult(null);
    try {
      await requestTestRun(Number(id));
      setRequestResult('done');
    } catch {
      setRequestResult('error');
    } finally {
      setRequesting(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectTestRuns(id)
      .then((data) => {
        if (cancelled) return;
        const parsed = data.map((run) => {
          if (!run.details || typeof run.details !== 'string') return run;
          try {
            return { ...run, details: JSON.parse(run.details) };
          } catch {
            return run;
          }
        });
        setTestRuns(parsed);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [id]);

  if (!project) {
    return <div className="empty-state">Project not found</div>;
  }

  if (loading) {
    return <div className="empty-state">Loading test results...</div>;
  }

  const selectedRun = selectedId ? testRuns.find((r) => r.id === selectedId) : null;

  if (selectedRun) {
    return (
      <div>
        <div className="page-title">
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setSelectedId(null);
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
      <div className="page-title">{project.prefix} &mdash; Test Results</div>
      <div className="test-actions">
        <button
          className="sync-btn"
          onClick={handleRunTests}
          disabled={requesting}
        >
          {requesting ? '$ requesting...' : '$ run tests'}
        </button>
        <span className="tooltip-trigger">
          ?
          <span className="tooltip-content">
            Alerts the team lead and PM to run the test suite for this project.
          </span>
        </span>
        {requestResult === 'done' && <span className="sync-btn__status">{'\u2713'} requested</span>}
        {requestResult === 'error' && <span className="sync-btn__status" style={{ color: 'var(--red)' }}>request failed</span>}
      </div>
      <div className="test-cadence">
        Tests run at the end of each sprint. Use the button above to request an ad-hoc run.
      </div>
      <div className="test-tab-bar">
        <button
          className={`test-tab${activeTab === 'results' ? ' test-tab--active' : ''}`}
          onClick={() => setActiveTab('results')}
        >
          Results
        </button>
        <button
          className={`test-tab${activeTab === 'performance' ? ' test-tab--active' : ''}`}
          onClick={() => setActiveTab('performance')}
        >
          Performance
        </button>
        <button
          className={`test-tab${activeTab === 'failures' ? ' test-tab--active' : ''}`}
          onClick={() => setActiveTab('failures')}
        >
          Failure Analysis
        </button>
      </div>
      {activeTab === 'results' && (
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
            <div className="empty-state">No test runs for this project</div>
          )}
        </div>
      )}
      {activeTab === 'performance' && (
        <TestPerformance projectId={id} />
      )}
      {activeTab === 'failures' && (
        <FailureAnalysis projectId={id} />
      )}
    </div>
  );
}

export default ProjectTestsPage;
