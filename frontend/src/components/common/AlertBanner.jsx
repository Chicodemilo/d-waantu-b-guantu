// Path: src/components/common/AlertBanner.jsx
// File: AlertBanner.jsx
// Created: 2026-03-29
// Purpose: Renders a dismissible alert banner with severity styling, category badge (DWB-464), agent/project source, and relative timestamp from the shared utils/format helpers (DWB-554: its private relativeTime parsed the API's naive-UTC timestamps as local time; the 7-day absolute fallback is preserved through the absoluteAfterDays option)
// Caller: DashboardPage.jsx, ProjectPage.jsx
// Callees: useStore, utils/format (relativeAge)
// Data In: props { alert } (alert object with severity, category, title, body, raised_by_agent_id, project_id, created_at)
// Data Out: default export AlertBanner component
// Last Modified: 2026-09-15 (DWB-554)

import useStore from '../../store/useStore';
import { relativeAge } from '../../utils/format';

// Alerts older than a week read better as a date than as "12d ago".
const ALERT_ABSOLUTE_AFTER_DAYS = 7;

function AlertBanner({ alert }) {
  const dismissAlert = useStore((s) => s.dismissAlert);
  const agent = useStore((s) => s.getAgent(alert.raised_by_agent_id));
  const project = useStore((s) => s.getProject(alert.project_id));

  const source = [project?.prefix.toLowerCase(), agent?.name].filter(Boolean).join(' / ');

  return (
    <div className={`alert-banner alert-banner--${alert.severity}`}>
      <div className="alert-banner__content">
        <div className="alert-banner__meta">
          {alert.category && (
            <span className={`alert-category-badge alert-category-badge--${alert.category}`}>
              {alert.category}
            </span>
          )}
          {alert.created_at && (
            <span className="alert-banner__time">{relativeAge(alert.created_at, Date.now(), { absoluteAfterDays: ALERT_ABSOLUTE_AFTER_DAYS })}</span>
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
