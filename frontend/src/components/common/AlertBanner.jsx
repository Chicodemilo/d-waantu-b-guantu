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
        <div className="alert-banner__agent">
          {source && <span>{source}</span>}
          {alert.created_at && <span className="alert-banner__time">{relativeTime(alert.created_at)}</span>}
        </div>
        <div className="alert-banner__title">{alert.title}</div>
        <div className="alert-banner__body">{alert.body}</div>
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
