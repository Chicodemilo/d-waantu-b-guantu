import '../../styles/common.css';

function StatusBadge({ status }) {
  const label = status.replace(/_/g, ' ');

  return (
    <span className={`status-badge status-badge--${status}`}>{label}</span>
  );
}

export default StatusBadge;
