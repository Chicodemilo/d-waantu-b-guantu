// Path: src/components/tests/TestCoverage.jsx
// File: TestCoverage.jsx
// Created: 2026-03-29
// Purpose: Fetches and displays test coverage table showing which routers have test files
// Caller: TestResultsPage.jsx
// Callees: react (useState, useEffect), api/status (getTestCoverage), tests.css
// Data In: None (fetches coverage data from API)
// Data Out: default export TestCoverage component
// Last Modified: 2026-03-29

import { useState, useEffect } from 'react';
import { getTestCoverage } from '../../api/status';
import '../../styles/tests.css';

function TestCoverage() {
  const [coverage, setCoverage] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getTestCoverage()
      .then((data) => {
        if (!cancelled) setCoverage(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading || !coverage) return null;

  const coveredCount = coverage.filter((r) => r.covered).length;

  return (
    <div className="test-coverage">
      <div className="test-coverage__header">
        Coverage: {coveredCount}/{coverage.length} routers
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Router</th>
            <th>Test File</th>
            <th>Covered</th>
          </tr>
        </thead>
        <tbody>
          {coverage.map((row) => (
            <tr key={row.router}>
              <td>{row.router}</td>
              <td className={row.test_file ? '' : 'test-coverage__missing'}>
                {row.test_file || 'missing'}
              </td>
              <td>
                <span className={row.covered ? 'test-coverage__icon--yes' : 'test-coverage__icon--no'}>
                  {row.covered ? '\u2713' : '\u2717'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default TestCoverage;
