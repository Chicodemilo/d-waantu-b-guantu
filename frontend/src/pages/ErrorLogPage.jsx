// Path: src/pages/ErrorLogPage.jsx
// File: ErrorLogPage.jsx
// Created: 2026-04-09
// Purpose: System-wide error log viewer with source/project filters and stack trace expansion
// Caller: App.jsx (route: /errors)
// Callees: react, ../api/errors, ../store/useStore, ../styles/errors.css
// Data In: Error logs from API, projects from store
// Data Out: Default export ErrorLogPage component
// Last Modified: 2026-04-09

import { useState, useEffect } from 'react';
import { getErrorLogs } from '../api/errors';
import useStore from '../store/useStore';
import '../styles/errors.css';

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

function sourceLabel(source) {
  if (source === 'backend') return 'BE';
  if (source === 'frontend') return 'FE';
  if (source === 'hook') return 'HK';
  return source;
}

function ErrorLogPage() {
  const projects = useStore((s) => s.projects);
  const [errors, setErrors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sourceFilter, setSourceFilter] = useState(null);
  const [projectFilter, setProjectFilter] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  const fetchErrors = async () => {
    const params = { limit: 100 };
    if (sourceFilter) params.source = sourceFilter;
    if (projectFilter) params.project_id = projectFilter;
    try {
      const data = await getErrorLogs(params);
      setErrors(data);
    } catch {
      // silently fail — ironic for an error page
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchErrors();
    const interval = setInterval(fetchErrors, 10000);
    return () => clearInterval(interval);
  }, [sourceFilter, projectFilter]);

  const sources = ['backend', 'frontend', 'hook'];

  return (
    <div className="dashboard">
      <div className="page-title">Error Log</div>

      <div className="error-log__filters">
        <div className="error-log__filter-group">
          <span className="error-log__filter-label">source:</span>
          <button
            className={`error-log__filter-btn${!sourceFilter ? ' error-log__filter-btn--active' : ''}`}
            onClick={() => setSourceFilter(null)}
          >
            all
          </button>
          {sources.map((s) => (
            <button
              key={s}
              className={`error-log__filter-btn${sourceFilter === s ? ' error-log__filter-btn--active' : ''}`}
              onClick={() => setSourceFilter(sourceFilter === s ? null : s)}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="error-log__filter-group">
          <span className="error-log__filter-label">project:</span>
          <button
            className={`error-log__filter-btn${!projectFilter ? ' error-log__filter-btn--active' : ''}`}
            onClick={() => setProjectFilter(null)}
          >
            all
          </button>
          {projects.filter((p) => p.status === 'active').map((p) => (
            <button
              key={p.id}
              className={`error-log__filter-btn${projectFilter === p.id ? ' error-log__filter-btn--active' : ''}`}
              onClick={() => setProjectFilter(projectFilter === p.id ? null : p.id)}
            >
              {p.prefix.toLowerCase()}
            </button>
          ))}
        </div>
        <button className="sync-btn" onClick={() => { setLoading(true); fetchErrors(); }}>
          $ refresh
        </button>
      </div>

      {loading && errors.length === 0 && (
        <div className="empty-state">Loading...</div>
      )}

      {!loading && errors.length === 0 && (
        <div className="empty-state">No errors logged. That's a good thing.</div>
      )}

      <div className="error-log__list">
        {errors.map((err) => {
          const isExpanded = expandedId === err.id;
          const project = err.project_id ? projects.find((p) => p.id === err.project_id) : null;
          return (
            <div key={err.id} className="error-log__row-wrapper">
              <div
                className={`error-log__row${isExpanded ? ' error-log__row--expanded' : ''}`}
                onClick={() => setExpandedId(isExpanded ? null : err.id)}
              >
                <span className="error-log__time">{formatTime(err.created_at)}</span>
                <span className={`error-log__source error-log__source--${err.source}`}>
                  [{sourceLabel(err.source)}]
                </span>
                {project && (
                  <span className="error-log__project">{project.prefix}</span>
                )}
                {err.status_code && (
                  <span className={`error-log__status-code${err.status_code >= 500 ? ' error-log__status-code--500' : ''}`}>
                    {err.status_code}
                  </span>
                )}
                <span className="error-log__endpoint">{err.endpoint || ''}</span>
                <span className="error-log__message">{err.message}</span>
              </div>
              {isExpanded && (
                <div className="error-log__detail">
                  {err.error_type && (
                    <div className="error-log__detail-row">
                      <span className="error-log__detail-label">type:</span>
                      <span className="error-log__detail-value">{err.error_type}</span>
                    </div>
                  )}
                  {err.file_path && (
                    <div className="error-log__detail-row">
                      <span className="error-log__detail-label">origin:</span>
                      <span className="error-log__detail-value">
                        {err.file_path}
                        {err.function_name ? `:${err.function_name}` : ''}
                        {err.line_number ? `:${err.line_number}` : ''}
                      </span>
                    </div>
                  )}
                  {err.stack_trace && (
                    <pre className="error-log__stack">{err.stack_trace}</pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ErrorLogPage;
