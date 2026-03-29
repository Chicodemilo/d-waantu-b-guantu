// Path: src/components/common/AsciiChart.jsx
// File: AsciiChart.jsx
// Created: 2026-03-29
// Purpose: Renders a horizontal bar chart using Unicode block characters with labels and values
// Caller: TokenOverview.jsx, FailureAnalysis.jsx, AgentMetrics.jsx
// Callees: charts.css
// Data In: props { title, tooltip, data[], maxBarWidth, colorClass }
// Data Out: default export AsciiChart component
// Last Modified: 2026-03-29

import '../../styles/charts.css';

function AsciiChart({ title, tooltip, data, maxBarWidth = 54, colorClass = '' }) {
  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="ascii-chart">
      {title && (
        <div className="ascii-chart__title">
          {title}
          {tooltip && (
            <span className="tooltip-trigger">?<span className="tooltip-content">{tooltip}</span></span>
          )}
        </div>
      )}
      {data.map((item, i) => {
        let filled = Math.round((item.value / maxValue) * maxBarWidth);
        if (item.value > 0 && filled === 0) filled = 1;
        const empty = maxBarWidth - filled;
        return (
          <div key={i} className="ascii-chart__row">
            <span className="ascii-chart__label">{item.label}</span>
            <span className="ascii-chart__track">
              <span className={`ascii-chart__bar${colorClass ? ` ascii-chart__bar--${colorClass}` : ''}`}>
                {'█'.repeat(filled)}
              </span>
              <span className="ascii-chart__bar-empty">{'░'.repeat(empty)}</span>
            </span>
            <span className="ascii-chart__value">
              {item.displayValue || item.value.toLocaleString()}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default AsciiChart;
