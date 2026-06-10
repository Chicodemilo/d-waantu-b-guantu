// Path: src/components/common/ErrorBoundary.jsx
// File: ErrorBoundary.jsx
// Created: 2026-06-10
// Purpose: React class-component error boundary that catches render-time exceptions in its subtree and renders a terminal-styled fallback instead of letting the whole app blank (DWB-370). Routes the catch through services/logger as a `render` category event (DWB-371) so the TL sees it in the lifecycle trail at /api/client-logs with route + componentStack context. Replaces the earlier direct POST to /api/errors so the catch surfaces in the same feed as the surrounding nav/fetch events.
// Caller: AppShell.jsx (wraps main content / Routes)
// Callees: react (Component), services/logger (log), error-boundary.css
// Data In: props { children, fallback? } - optional render-prop fallback (error, reset) => ReactNode
// Data Out: default export ErrorBoundary class component
// Last Modified: 2026-06-10

import { Component } from 'react';
import { log } from '../../services/logger';
import '../../styles/error-boundary.css';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
    this.handleReset = this.handleReset.bind(this);
    this.handleReload = this.handleReload.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    try {
      log.error(
        'render',
        (error?.message || 'Unknown render error').slice(0, 2000),
        {
          error_name: error?.name || 'RenderError',
          componentStack: (info?.componentStack || '').slice(0, 10000),
          stack: (error?.stack || '').slice(0, 10000),
        }
      );
    } catch {}
  }

  handleReset() {
    this.setState({ error: null, info: null });
  }

  handleReload() {
    if (typeof window !== 'undefined') window.location.reload();
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (typeof this.props.fallback === 'function') {
      return this.props.fallback(error, this.handleReset);
    }

    return (
      <div className="error-boundary" role="alert">
        <div className="error-boundary__title">Something went wrong</div>
        <div className="error-boundary__message">
          The page hit an unexpected error and could not render.
        </div>
        <div className="error-boundary__detail">{error.message || String(error)}</div>
        <div className="error-boundary__actions">
          <button type="button" className="error-boundary__action" onClick={this.handleReload}>
            reload
          </button>
          <button type="button" className="error-boundary__action" onClick={this.handleReset}>
            dismiss
          </button>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
