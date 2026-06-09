// Path: src/components/common/AsciiProgressBar.jsx
// File: AsciiProgressBar.jsx
// Created: 2026-03-29
// Purpose: Renders a Unicode block-character progress bar with percentage display
// Caller: ProjectCard.jsx, EpicDetail.jsx, EpicList.jsx, SprintDetail.jsx, SprintProgress.jsx
// Callees: charts.css
// Data In: props { value, max, width }
// Data Out: default export AsciiProgressBar component
// Last Modified: 2026-06-09

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
