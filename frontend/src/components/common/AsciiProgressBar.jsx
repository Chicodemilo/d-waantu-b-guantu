import '../../styles/charts.css';

function AsciiProgressBar({ value, max = 100, width = 20 }) {
  const pct = Math.min(Math.round((value / max) * 100), 100);
  const filled = Math.round((pct / 100) * width);
  const empty = width - filled;

  return (
    <span className="progress-bar">
      <span className="progress-bar__track">
        [
        <span className="progress-bar__filled">{'█'.repeat(filled)}</span>
        <span className="progress-bar__empty">{'░'.repeat(empty)}</span>
        ]
      </span>
      <span className="progress-bar__pct">{pct}%</span>
    </span>
  );
}

export default AsciiProgressBar;
