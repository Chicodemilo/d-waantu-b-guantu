// Path: src/components/common/AlertBanner.jsx
// File: AlertBanner.jsx
// Created: 2026-03-29
// Purpose: Renders a dismissible alert banner with severity styling, agent/project source, and relative timestamp
// Caller: DashboardPage.jsx, ProjectPage.jsx
// Callees: useStore, common.css
// Data In: props { alert } (alert object with severity, title, body, raised_by_agent_id, project_id, created_at)
// Data Out: default export AlertBanner component
// Last Modified: 2026-03-29

import useStore from '../../store/useStore';
import '../../styles/common.css';

function relativeTime(ts) {
  if (!ts) return '';
  const now = Date.now();
  const diff = now - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

function AlertBanner({ alert }) {
  const dismissAlert = useStore((s) => s.dismissAlert);
  const agent = useStore((s) => s.getAgent(alert.raised_by_agent_id));
  const project = useStore((s) => s.getProject(alert.project_id));

  const source = [project?.prefix.toLowerCase(), agent?.name].filter(Boolean).join(' / ');

  return (
    <div className={`alert-banner alert-banner--${alert.severity}`}>
      <div className="alert-banner__content">
        <div className="alert-banner__meta">
          {alert.created_at && (
            <span className="alert-banner__time">{relativeTime(alert.created_at)}</span>
          )}
          {alert.created_at && source && <span className="alert-banner__sep">::</span>}
          {source && <span className="alert-banner__source">{source}</span>}
          {(alert.created_at || source) && alert.body && (
            <span className="alert-banner__sep">::</span>
          )}
          {alert.body && <span className="alert-banner__body-inline">{alert.body}</span>}
        </div>
        <div className="alert-banner__title">{alert.title}</div>
      </div>
      <button
        className="alert-banner__dismiss"
        onClick={() => dismissAlert(alert.id)}
        title="Dismiss"
      >
        x
      </button>
    </div>
  );
}

export default AlertBanner;
